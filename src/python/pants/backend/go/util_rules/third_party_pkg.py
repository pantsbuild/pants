# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import ijson.backends.python as ijson

from pants.backend.go.go_sources.load_go_binary import LoadedGoBinaryRequest, setup_go_binary
from pants.backend.go.util_rules import pkg_analyzer
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.cgo import CGoCompilerFlags
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.backend.go.util_rules.pkg_analyzer import PackageAnalyzerSetup
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestSubset,
    FileContent,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.intrinsics import (
    create_digest,
    digest_to_snapshot,
    execute_process,
    get_digest_contents,
    merge_digests,
)
from pants.engine.process import Process, fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.dirutil import group_by_dir
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


class GoThirdPartyPkgError(Exception):
    pass


@dataclass(frozen=True)
class ThirdPartyPkgAnalysis:
    """All the info and files needed to build a third-party package.

    The digest only contains the files for the package, with all prefixes stripped.
    """

    import_path: str
    name: str

    digest: Digest
    dir_path: str

    # Note that we don't care about test-related metadata like `TestImports`, as we'll never run
    # tests directly on a third-party package.
    imports: tuple[str, ...]
    go_files: tuple[str, ...]
    cgo_files: tuple[str, ...]
    cgo_flags: CGoCompilerFlags

    c_files: tuple[str, ...]
    cxx_files: tuple[str, ...]
    m_files: tuple[str, ...]
    h_files: tuple[str, ...]
    f_files: tuple[str, ...]
    s_files: tuple[str, ...]

    syso_files: tuple[str, ...]

    minimum_go_version: str | None

    embed_patterns: tuple[str, ...]
    test_embed_patterns: tuple[str, ...]
    xtest_embed_patterns: tuple[str, ...]

    embed_config: EmbedConfig | None = None
    test_embed_config: EmbedConfig | None = None
    xtest_embed_config: EmbedConfig | None = None

    error: GoThirdPartyPkgError | None = None


@dataclass(frozen=True)
class ThirdPartyPkgAnalysisRequest(EngineAwareParameter):
    """Request the info and digest needed to build a third-party package.

    The package's module must be included in the input `go.mod`/`go.sum`.
    """

    import_path: str
    go_mod_address: Address
    go_mod_digest: Digest
    go_mod_path: str
    build_opts: GoBuildOptions

    def debug_hint(self) -> str:
        return f"{self.import_path} from {self.go_mod_path}"


@dataclass(frozen=True)
class AllThirdPartyPackages:
    """All the packages downloaded from a go.mod, along with a digest of the downloaded files.

    The digest has files in the format `gopath/pkg/mod`, which is what `GoSdkProcess` sets `GOPATH`
    to. This means that you can include the digest in a process and Go will properly consume it as
    the `GOPATH`.
    """

    digest: Digest
    import_paths_to_pkg_info: FrozenDict[str, ThirdPartyPkgAnalysis]


@dataclass(frozen=True)
class AllThirdPartyPackagesRequest:
    go_mod_address: Address
    go_mod_digest: Digest
    go_mod_path: str
    build_opts: GoBuildOptions


@dataclass(frozen=True)
class ModuleDescriptorsRequest:
    digest: Digest
    path: str


@dataclass(frozen=True)
class ModuleDescriptor:
    import_path: str
    name: str
    version: str
    indirect: bool
    minimum_go_version: str | None


@dataclass(frozen=True)
class ModuleDescriptors:
    modules: FrozenOrderedSet[ModuleDescriptor]
    go_mods_digest: Digest


@dataclass(frozen=True)
class ModuleDownloadRequest:
    """Download and analyze a Go module, keyed by (name, version, minimum_go_version,
    build_opts, go_sum_entries).

    This enables cross-go.mod deduplication: if mod-a and mod-b both depend on
    grpc@v1.60.0 with the same go.sum entries, the download and analysis only
    happens once because the Pants engine memoizes by the full request key.

    ``go_sum_entries`` carries the two go.sum lines for ``<name> <version>`` and
    ``<name> <version>/go.mod`` extracted from the consuming go.mod's real
    go.sum. These entries are content-addressable by design: two well-formed
    go.sums MUST agree on them for the same module@version. Including them in
    the dedup key has two effects:

    1. Happy path: all consumers of module@version share one download, and the
       synthetic go.sum written into the sandbox lets Go perform its normal
       checksum verification (no GONOSUMCHECK override).
    2. Tampered path: if one go.sum disagrees, the two consumers produce
       distinct requests -- each verified independently against its own
       entries -- and the tampered one fails with Go's usual SECURITY ERROR.
    """

    name: str
    version: str
    minimum_go_version: str | None
    build_opts: GoBuildOptions
    go_sum_entries: tuple[str, ...]


@dataclass(frozen=True)
class AnalyzedThirdPartyModule:
    packages: FrozenOrderedSet[ThirdPartyPkgAnalysis]


@dataclass(frozen=True)
class AnalyzeThirdPartyPackageRequest:
    pkg_json: FrozenDict[str, Any]
    module_sources_digest: Digest
    module_sources_path: str
    module_import_path: str
    package_path: str
    minimum_go_version: str | None


@dataclass(frozen=True)
class FallibleThirdPartyPkgAnalysis:
    """Metadata for a third-party Go package, but fallible if our analysis failed."""

    analysis: ThirdPartyPkgAnalysis | None
    import_path: str
    exit_code: int = 0
    stderr: str | None = None


@rule
async def analyze_module_dependencies(request: ModuleDescriptorsRequest) -> ModuleDescriptors:
    # List the modules used directly and indirectly by this module.
    #
    # This rule can't modify `go.mod` and `go.sum` as it would require mutating the workspace.
    # Instead, we expect them to be well-formed already.
    #
    # Options used:
    # - `-mod=readonly': It would be convenient to set `-mod=mod` to allow edits, and then compare the
    #   resulting files to the input so that we could print a diff for the user to know how to update. But
    #   `-mod=mod` results in more packages being downloaded and added to `go.mod` than is
    #   actually necessary.
    # TODO: nice error when `go.mod` and `go.sum` would need to change. Right now, it's a
    #  message from Go and won't be intuitive for Pants users what to do.
    # - `-e` is used to not fail if one of the modules is problematic. There may be some packages in the transitive
    #   closure that cannot be built, but we should  not blow up Pants. For example, a package that sets the
    #   special value `package documentation` and has no source files would naively error due to
    #   `build constraints exclude all Go files`, even though we should not error on that package.
    mod_list_result = await fallible_to_exec_result_or_raise(
        **implicitly(
            GoSdkProcess(
                command=["list", "-mod=readonly", "-e", "-m", "-json", "all"],
                input_digest=request.digest,
                output_directories=("gopath",),
                working_dir=request.path if request.path else None,
                # Allow downloads of the module metadata (i.e., go.mod files).
                allow_downloads=True,
                description="Analyze Go module dependencies.",
            )
        )
    )

    if len(mod_list_result.stdout) == 0:
        return ModuleDescriptors(FrozenOrderedSet(), EMPTY_DIGEST)

    descriptors: dict[tuple[str, str], ModuleDescriptor] = {}

    for mod_json in ijson.items(mod_list_result.stdout, "", multiple_values=True):
        # Skip the first-party module being analyzed.
        if "Main" in mod_json and mod_json["Main"]:
            continue

        # Skip first-party modules referenced from other first-party modules.
        # TODO Issue #22097: These cross-module references could be used for dependency inference
        if "Replace" in mod_json and "Version" not in mod_json["Replace"]:
            continue

        if "Replace" in mod_json:
            # TODO: Reject local file path replacements? Gazelle does.
            name = mod_json["Replace"]["Path"]
            version = mod_json["Replace"]["Version"]
        else:
            name = mod_json["Path"]
            version = mod_json["Version"]

        descriptors[(name, version)] = ModuleDescriptor(
            import_path=mod_json["Path"],
            name=name,
            version=version,
            indirect=mod_json.get("Indirect", False),
            minimum_go_version=mod_json.get("GoVersion"),
        )

    # TODO: Augment the modules with go.sum entries?
    # Gazelle does this, mainly to store the sum on the go_repository rule. We could store it (or its
    # absence) to be able to download sums automatically.

    return ModuleDescriptors(FrozenOrderedSet(descriptors.values()), mod_list_result.output_digest)


def strip_sandbox_prefix(path: str, marker: str) -> str:
    """Strip a path prefix from a path using a marker string to find the start of the portion to not
    strip. This is used to strip absolute paths used in the execution sandbox by `go`.

    Note: The marker string is required because we cannot assume how the prefix will be formed since it
    will differ depending on which execution environment is used (e.g, local or remote).
    """
    marker_pos = path.find(marker)
    if marker_pos != -1:
        return path[marker_pos:]
    else:
        return path


def _parse_go_sum(go_sum_content: bytes) -> dict[tuple[str, str], tuple[str, ...]]:
    """Parse a go.sum file into a dict keyed by (module name, version).

    A well-formed go.sum has up to two lines per (module, version):

        <name> <version> h1:<content hash>=
        <name> <version>/go.mod h1:<go.mod hash>=

    Returns a dict mapping (name, version) to a tuple of the matching lines,
    enabling O(1) lookup per module instead of re-scanning the file.
    """
    entries: dict[tuple[str, str], list[str]] = {}
    for line in go_sum_content.decode("utf-8").splitlines():
        if not line:
            continue
        parts = line.split(" ", 2)
        if len(parts) < 3:
            continue
        name = parts[0]
        version_field = parts[1]
        # Strip the "/go.mod" suffix to get the base version for grouping.
        version = version_field.removesuffix("/go.mod")
        key = (name, version)
        entries.setdefault(key, []).append(line)
    return {k: tuple(v) for k, v in entries.items()}


def _extract_go_sum_entries_for_module(
    go_sum_content: bytes, name: str, version: str
) -> tuple[str, ...]:
    """Return the go.sum lines for a given module@version.

    Thin wrapper around _parse_go_sum for callers that only need one module.
    Prefer _parse_go_sum when looking up multiple modules from the same go.sum.
    """
    parsed = _parse_go_sum(go_sum_content)
    return parsed.get((name, version), ())


def _freeze_json_dict(d: dict[Any, Any]) -> FrozenDict[str, Any]:
    result = {}
    for k, v in d.items():
        if not isinstance(k, str):
            raise AssertionError("Got non-`str` key for _freeze_json_dict.")

        f: Any = None
        if isinstance(v, list):
            f = tuple(v)
        elif isinstance(v, dict):
            f = _freeze_json_dict(v)
        elif isinstance(v, str) or isinstance(v, int):
            f = v
        else:
            raise AssertionError(f"Unsupported value type for _freeze_json_dict: {type(v)}")
        result[k] = f
    return FrozenDict(result)


@rule
async def analyze_go_third_party_package(
    request: AnalyzeThirdPartyPackageRequest,
) -> FallibleThirdPartyPkgAnalysis:
    if not request.package_path.startswith(request.module_sources_path):
        raise AssertionError(
            "The path within GOPATH for a package in a module must always be prefixed by the path "
            "to the applicable module's root directory. "
            f"This was not the case however for module {request.module_import_path}.\n\n"
            "This may be a bug in Pants. Please report this issue at "
            "https://github.com/pantsbuild/pants/issues/new/choose and include the following data: "
            f"package_path: {request.package_path}; module_sources_path: {request.module_sources_path}; "
            f"module_import_path: {request.module_import_path}"
        )
    import_path_tail = request.package_path[len(request.module_sources_path) :].strip(os.sep)
    if import_path_tail != "":
        parts = import_path_tail.split(os.sep)
        import_path = "/".join([request.module_import_path, *parts])
    else:
        import_path = request.module_import_path

    if "Error" in request.pkg_json or "InvalidGoFiles" in request.pkg_json:
        error = request.pkg_json.get("Error", "")
        if error:
            error += "\n"
        if "InvalidGoFiles" in request.pkg_json:
            error += "\n".join(
                f"{filename}: {error}"
                for filename, error in request.pkg_json.get("InvalidGoFiles", {}).items()
            )
            error += "\n"
        return FallibleThirdPartyPkgAnalysis(
            analysis=None, import_path=import_path, exit_code=1, stderr=error
        )

    maybe_error: GoThirdPartyPkgError | None = None

    for key in (
        "CompiledGoFiles",
        "SwigFiles",
        "SwigCXXFiles",
    ):
        if key in request.pkg_json:
            maybe_error = GoThirdPartyPkgError(
                f"The third-party package {import_path} includes `{key}`, which Pants does "
                "not yet support. Please open a feature request at "
                "https://github.com/pantsbuild/pants/issues/new/choose so that we know to "
                "prioritize adding support. Please include this error message and the version of "
                "the third-party module."
            )

    analysis = ThirdPartyPkgAnalysis(
        digest=request.module_sources_digest,
        import_path=import_path,
        name=request.pkg_json["Name"],
        dir_path=request.package_path,
        imports=tuple(request.pkg_json.get("Imports", ())),
        go_files=tuple(request.pkg_json.get("GoFiles", ())),
        c_files=tuple(request.pkg_json.get("CFiles", ())),
        cxx_files=tuple(request.pkg_json.get("CXXFiles", ())),
        m_files=tuple(request.pkg_json.get("MFiles", ())),
        h_files=tuple(request.pkg_json.get("HFiles", ())),
        f_files=tuple(request.pkg_json.get("FFiles", ())),
        s_files=tuple(request.pkg_json.get("SFiles", ())),
        syso_files=tuple(request.pkg_json.get("SysoFiles", ())),
        cgo_files=tuple(request.pkg_json.get("CgoFiles", ())),
        minimum_go_version=request.minimum_go_version,
        embed_patterns=tuple(request.pkg_json.get("EmbedPatterns", [])),
        test_embed_patterns=tuple(request.pkg_json.get("TestEmbedPatterns", [])),
        xtest_embed_patterns=tuple(request.pkg_json.get("XTestEmbedPatterns", [])),
        error=maybe_error,
        cgo_flags=CGoCompilerFlags(
            cflags=tuple(request.pkg_json.get("CgoCFLAGS", [])),
            cppflags=tuple(request.pkg_json.get("CgoCPPFLAGS", [])),
            cxxflags=tuple(request.pkg_json.get("CgoCXXFLAGS", [])),
            fflags=tuple(request.pkg_json.get("CgoFFLAGS", [])),
            ldflags=tuple(request.pkg_json.get("CgoLDFLAGS", [])),
            pkg_config=tuple(request.pkg_json.get("CgoPkgConfig", [])),
        ),
    )

    if analysis.embed_patterns or analysis.test_embed_patterns or analysis.xtest_embed_patterns:
        patterns_json = json.dumps(
            {
                "EmbedPatterns": analysis.embed_patterns,
                "TestEmbedPatterns": analysis.test_embed_patterns,
                "XTestEmbedPatterns": analysis.xtest_embed_patterns,
            }
        ).encode("utf-8")
        embedder, patterns_json_digest = await concurrently(
            setup_go_binary(
                LoadedGoBinaryRequest("embedcfg", ("main.go",), "./embedder"), **implicitly()
            ),
            create_digest(CreateDigest([FileContent("patterns.json", patterns_json)])),
        )
        input_digest = await merge_digests(
            MergeDigests((request.module_sources_digest, patterns_json_digest, embedder.digest))
        )
        embed_result = await execute_process(
            Process(
                ("./embedder", "patterns.json", request.package_path),
                input_digest=input_digest,
                description=f"Create embed mapping for {import_path}",
                level=LogLevel.DEBUG,
            ),
            **implicitly(),
        )
        if embed_result.exit_code != 0:
            return FallibleThirdPartyPkgAnalysis(
                analysis=None,
                import_path=import_path,
                exit_code=1,
                stderr=embed_result.stderr.decode(),
            )
        metadata = json.loads(embed_result.stdout)
        embed_config = EmbedConfig.from_json_dict(metadata.get("EmbedConfig", {}))
        test_embed_config = EmbedConfig.from_json_dict(metadata.get("TestEmbedConfig", {}))
        xtest_embed_config = EmbedConfig.from_json_dict(metadata.get("XTestEmbedConfig", {}))
        analysis = dataclasses.replace(
            analysis,
            embed_config=embed_config,
            test_embed_config=test_embed_config,
            xtest_embed_config=xtest_embed_config,
        )

    return FallibleThirdPartyPkgAnalysis(
        analysis=analysis,
        import_path=import_path,
        exit_code=0,
        stderr=None,
    )


@rule
async def download_and_analyze_module(
    request: ModuleDownloadRequest,
    analyzer: PackageAnalyzerSetup,
) -> AnalyzedThirdPartyModule:
    """Download and analyze a single Go module via a synthetic go.mod + go.sum.

    Keyed by (name, version, minimum_go_version, build_opts, go_sum_entries),
    which lets the Pants engine deduplicate identical module downloads across
    go.mods.

    A synthetic go.mod + go.sum pair is written into the sandbox so that Go's
    normal checksum verification still runs -- the go.sum entries come straight
    from the consuming go.mod's real go.sum (see ModuleDownloadRequest for the
    full argument for why this is safe).
    """
    # Create a synthetic go.mod (and go.sum when entries are available) that
    # only requires this one module. When the consuming go.sum contains the
    # entries for this module@version, we emit them verbatim so `go mod
    # download` performs its usual local checksum verification. When they
    # are absent (e.g., a transitive discovered during MVS that the consumer's
    # go.sum hasn't recorded yet, or a go.sum that is entirely missing), we
    # omit the synthetic go.sum and let Go fall back to GOSUMDB
    # (sum.golang.org by default) for verification. This is a softer signal
    # than the pre-dedup rule, which raised an error pointing the user at
    # `go mod download all`; the warning below preserves that guidance.
    if not request.go_sum_entries:
        logger.warning(
            "No go.sum entries found for %s@%s; falling back to GOSUMDB for "
            "checksum verification. This usually means the consuming go.mod's "
            "go.sum is incomplete -- run `go mod download all` (or `go mod "
            "tidy`) in that module's directory to record the checksum locally.",
            request.name,
            request.version,
        )
    go_version = request.minimum_go_version or "1.21"
    synthetic_go_mod = (
        f"module synthetic.invalid\n\ngo {go_version}\n\nrequire {request.name} {request.version}\n"
    )
    synthetic_files = [FileContent("go.mod", synthetic_go_mod.encode())]
    if request.go_sum_entries:
        synthetic_go_sum = "\n".join(request.go_sum_entries) + "\n"
        synthetic_files.append(FileContent("go.sum", synthetic_go_sum.encode()))
    synthetic_digest = await create_digest(CreateDigest(synthetic_files))

    download_result = await fallible_to_exec_result_or_raise(
        **implicitly(
            GoSdkProcess(
                ("mod", "download", "-json", f"{request.name}@{request.version}"),
                input_digest=synthetic_digest,
                allow_downloads=True,
                output_directories=("gopath",),
                description=f"Download Go module {request.name}@{request.version}.",
            )
        )
    )

    if len(download_result.stdout) == 0:
        raise AssertionError(
            f"Expected output from `go mod download` for {request.name}@{request.version}."
        )

    module_metadata = json.loads(download_result.stdout)
    module_sources_relpath = strip_sandbox_prefix(module_metadata["Dir"], "gopath/")
    go_mod_relpath = strip_sandbox_prefix(module_metadata["GoMod"], "gopath/")

    module_sources_snapshot = await digest_to_snapshot(
        **implicitly(
            DigestSubset(
                download_result.output_digest,
                PathGlobs(
                    [f"{module_sources_relpath}/**", go_mod_relpath],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    conjunction=GlobExpansionConjunction.all_match,
                    description_of_origin=f"the download of Go module {request.name}@{request.version}",
                ),
            )
        )
    )

    candidate_package_dirs = []
    files_by_dir = group_by_dir(
        p for p in module_sources_snapshot.files if p.startswith(module_sources_relpath)
    )
    for maybe_pkg_dir, files in files_by_dir.items():
        # Skip directories where "testdata" would end up in the import path.
        # See https://github.com/golang/go/blob/f005df8b582658d54e63d59953201299d6fee880/src/go/build/build.go#L580-L585
        if "testdata" in maybe_pkg_dir.split("/"):
            continue
        if any(f for f in files if f.endswith(".go")):
            candidate_package_dirs.append(maybe_pkg_dir)
    candidate_package_dirs.sort()

    analyzer_relpath = "__analyzer"
    analysis_result = await fallible_to_exec_result_or_raise(
        **implicitly(
            Process(
                [os.path.join(analyzer_relpath, analyzer.path), *candidate_package_dirs],
                input_digest=module_sources_snapshot.digest,
                immutable_input_digests={
                    analyzer_relpath: analyzer.digest,
                },
                description=f"Analyze metadata for Go third-party module: {request.name}@{request.version}",
                level=LogLevel.DEBUG,
                env={"CGO_ENABLED": "1" if request.build_opts.cgo_enabled else "0"},
            )
        )
    )

    if len(analysis_result.stdout) == 0:
        return AnalyzedThirdPartyModule(FrozenOrderedSet())

    package_analysis_gets = []
    for pkg_path, pkg_json in zip(
        candidate_package_dirs, ijson.items(analysis_result.stdout, "", multiple_values=True)
    ):
        package_analysis_gets.append(
            analyze_go_third_party_package(
                AnalyzeThirdPartyPackageRequest(
                    pkg_json=_freeze_json_dict(pkg_json),
                    module_sources_digest=module_sources_snapshot.digest,
                    module_sources_path=module_sources_relpath,
                    module_import_path=request.name,
                    package_path=pkg_path,
                    minimum_go_version=request.minimum_go_version,
                )
            )
        )
    analyzed_packages_fallible = await concurrently(package_analysis_gets)
    analyzed_packages = [
        pkg.analysis for pkg in analyzed_packages_fallible if pkg.analysis and pkg.exit_code == 0
    ]
    return AnalyzedThirdPartyModule(FrozenOrderedSet(analyzed_packages))


@rule(desc="Download and analyze all third-party Go packages", level=LogLevel.DEBUG)
async def download_and_analyze_third_party_packages(
    request: AllThirdPartyPackagesRequest,
) -> AllThirdPartyPackages:
    module_analysis = await analyze_module_dependencies(
        ModuleDescriptorsRequest(
            digest=request.go_mod_digest,
            path=os.path.dirname(request.go_mod_path),
        )
    )

    # Read the real go.sum once so we can extract per-module entries for the
    # download sandbox. This keeps Go's checksum verification intact while
    # allowing the engine to memoize identical module@version downloads
    # across different go.mods.
    go_sum_path = os.path.join(os.path.dirname(request.go_mod_path), "go.sum")
    digest_contents = await get_digest_contents(request.go_mod_digest)
    go_sum_content = b""
    for entry in digest_contents:
        if entry.path == go_sum_path:
            go_sum_content = entry.content
            break

    # Parse the go.sum once into a dict for O(1) lookup per module.
    go_sum_index = _parse_go_sum(go_sum_content)

    # The engine memoizes by (name, version, minimum_go_version, build_opts,
    # go_sum_entries), so identical modules across go.mods are downloaded
    # once -- reducing downloads from O(N*M) to O(M).
    analyzed_modules = await concurrently(
        download_and_analyze_module(
            ModuleDownloadRequest(
                name=mod.name,
                version=mod.version,
                minimum_go_version=mod.minimum_go_version,
                build_opts=request.build_opts,
                go_sum_entries=go_sum_index.get((mod.name, mod.version), ()),
            ),
            **implicitly(),
        )
        for mod in module_analysis.modules
    )

    import_path_to_info = {
        pkg.import_path: pkg
        for analyzed_module in analyzed_modules
        for pkg in analyzed_module.packages
    }

    return AllThirdPartyPackages(EMPTY_DIGEST, FrozenDict(import_path_to_info))


@rule
async def extract_package_info(request: ThirdPartyPkgAnalysisRequest) -> ThirdPartyPkgAnalysis:
    all_packages = await download_and_analyze_third_party_packages(
        AllThirdPartyPackagesRequest(
            request.go_mod_address,
            request.go_mod_digest,
            request.go_mod_path,
            build_opts=request.build_opts,
        )
    )
    pkg_info = all_packages.import_paths_to_pkg_info.get(request.import_path)
    if pkg_info:
        return pkg_info
    raise AssertionError(
        f"The package `{request.import_path}` was not downloaded, but Pants tried using it. "
        "This should not happen. Please open an issue at "
        "https://github.com/pantsbuild/pants/issues/new/choose with this error message."
    )


def maybe_raise_or_create_error_or_create_failed_pkg_info(
    go_list_json: dict, import_path: str
) -> tuple[GoThirdPartyPkgError | None, ThirdPartyPkgAnalysis | None]:
    """Error for unrecoverable errors, otherwise lazily create an error or `ThirdPartyPkgInfo` for
    recoverable errors.

    Lazy errors should only be raised when the package is compiled, but not during target generation
    and project introspection. This is important so that we don't overzealously error on packages
    that the user doesn't actually ever use, given how a Go module includes all of its packages,
    even test packages that are never used by first-party code.

    Returns a `ThirdPartyPkgInfo` if the `Dir` key is missing, which is necessary for our normal
    analysis of the package.
    """
    if import_path == "...":
        if "Error" not in go_list_json:
            raise AssertionError(
                "`go list` included the import path `...`, but there was no `Error` attached. "
                "Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose "
                f"with this error message:\n\n{go_list_json}"
            )
        # TODO: Improve this error message, such as better instructions if `go.sum` is stale.
        raise GoThirdPartyPkgError(go_list_json["Error"]["Err"])

    if "Dir" not in go_list_json:
        error = GoThirdPartyPkgError(
            f"`go list` failed for the import path `{import_path}` because `Dir` was not defined. "
            f"Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose so "
            f"that we can figure out how to support this:"
            f"\n\n{go_list_json}"
        )
        return None, ThirdPartyPkgAnalysis(
            import_path=import_path,
            name="",
            dir_path="",
            digest=EMPTY_DIGEST,
            imports=(),
            go_files=(),
            c_files=(),
            cxx_files=(),
            h_files=(),
            m_files=(),
            f_files=(),
            s_files=(),
            syso_files=(),
            minimum_go_version=None,
            embed_patterns=(),
            test_embed_patterns=(),
            xtest_embed_patterns=(),
            error=error,
            cgo_files=(),
            cgo_flags=CGoCompilerFlags(
                cflags=(),
                cppflags=(),
                cxxflags=(),
                fflags=(),
                ldflags=(),
                pkg_config=(),
            ),
        )

    if "Error" in go_list_json:
        err_msg = go_list_json["Error"]["Err"]
        return (
            GoThirdPartyPkgError(
                f"`go list` failed for the import path `{import_path}`. Please open an issue at "
                "https://github.com/pantsbuild/pants/issues/new/choose so that we can figure out "
                "how to support this:"
                f"\n\n{err_msg}\n\n{go_list_json}"
            ),
            None,
        )

    return None, None


def rules():
    return (
        *collect_rules(),
        *pkg_analyzer.rules(),
    )
