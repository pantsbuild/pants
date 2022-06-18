# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pants.backend.go.go_sources import load_go_binary
from pants.backend.go.go_sources.load_go_binary import LoadedGoBinary, LoadedGoBinaryRequest
from pants.backend.go.target_types import GoPackageSourcesField
from pants.backend.go.util_rules import pkg_analyzer
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.backend.go.util_rules.pkg_analyzer import PackageAnalyzerSetup
from pants.build_graph.address import Address
from pants.core.target_types import ResourceSourceField
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests, RemovePrefix
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Targets,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.util.dirutil import fast_relpath
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirstPartyPkgImportPath:
    """The derived import path of a first party package, based on its owning go.mod.

    Use `FirstPartyPkgAnalysis` instead for more detailed information like parsed imports. Use
    `FirstPartyPkgDigest` for source files and embed config.
    """

    import_path: str
    dir_path_rel_to_gomod: str


@dataclass(frozen=True)
class FirstPartyPkgImportPathRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str:
        return self.address.spec


@dataclass(frozen=True)
class FirstPartyPkgAnalysis:
    """All the metadata for a first-party Go package.

    `dir_path` is relative to the build root.

    Use `FirstPartyPkgImportPath` if you only need the derived import path. Use
    `FirstPartyPkgDigest` for the source files and embed config.
    """

    import_path: str
    dir_path: str

    imports: tuple[str, ...]
    test_imports: tuple[str, ...]
    xtest_imports: tuple[str, ...]

    go_files: tuple[str, ...]
    test_go_files: tuple[str, ...]
    xtest_go_files: tuple[str, ...]

    s_files: tuple[str, ...]

    minimum_go_version: str | None

    embed_patterns: tuple[str, ...]
    test_embed_patterns: tuple[str, ...]
    xtest_embed_patterns: tuple[str, ...]


@dataclass(frozen=True)
class FallibleFirstPartyPkgAnalysis:
    """Metadata for a Go package, but fallible if our analysis failed."""

    analysis: FirstPartyPkgAnalysis | None
    import_path: str
    exit_code: int = 0
    stderr: str | None = None

    @classmethod
    def from_process_result(
        cls,
        result: FallibleProcessResult,
        *,
        dir_path: str,
        import_path: str,
        minimum_go_version: str,
        description_of_source: str,
    ) -> FallibleFirstPartyPkgAnalysis:
        if result.exit_code != 0:
            return cls(
                analysis=None,
                import_path=import_path,
                exit_code=result.exit_code,
                stderr=(
                    f"Failed to analyze Go sources generated from {import_path}.\n\n"
                    "This may be a bug in Pants. Please report this issue at "
                    "https://github.com/pantsbuild/pants/issues/new/choose and include the following data: "
                    f"error:\n{result.stderr.decode()}"
                ),
            )

        try:
            metadata = json.loads(result.stdout)
        except json.JSONDecodeError as ex:
            return cls(
                analysis=None,
                import_path=import_path,
                exit_code=1,
                stderr=f"Failed to decode JSON document from analysis: {ex}",
            )

        if "Error" in metadata or "InvalidGoFiles" in metadata:
            error = metadata.get("Error", "")
            if error:
                error += "\n"
            if "InvalidGoFiles" in metadata:
                error += "\n".join(
                    f"{filename}: {error}"
                    for filename, error in metadata.get("InvalidGoFiles", {}).items()
                )
                error += "\n"
            return cls(analysis=None, import_path=import_path, exit_code=1, stderr=error)

        if "CgoFiles" in metadata:
            return cls(
                analysis=None,
                import_path=import_path,
                exit_code=1,
                stderr=(
                    f"The {description_of_source} includes `CgoFiles`, which Pants does "
                    "not yet support. Please open a feature request at "
                    "https://github.com/pantsbuild/pants/issues/new/choose so that we know to "
                    "prioritize adding support.\n\n"
                ),
            )

        analysis = FirstPartyPkgAnalysis(
            dir_path=dir_path,
            import_path=import_path,
            imports=tuple(metadata.get("Imports", [])),
            test_imports=tuple(metadata.get("TestImports", [])),
            xtest_imports=tuple(metadata.get("XTestImports", [])),
            go_files=tuple(metadata.get("GoFiles", [])),
            test_go_files=tuple(metadata.get("TestGoFiles", [])),
            xtest_go_files=tuple(metadata.get("XTestGoFiles", [])),
            s_files=tuple(metadata.get("SFiles", [])),
            minimum_go_version=minimum_go_version,
            embed_patterns=tuple(metadata.get("EmbedPatterns", [])),
            test_embed_patterns=tuple(metadata.get("TestEmbedPatterns", [])),
            xtest_embed_patterns=tuple(metadata.get("XTestEmbedPatterns", [])),
        )
        return cls(analysis, import_path)


@dataclass(frozen=True)
class FirstPartyPkgAnalysisRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str:
        return self.address.spec


@dataclass(frozen=True)
class FirstPartyPkgDigest:
    """The source files needed to build the package."""

    digest: Digest
    embed_config: EmbedConfig | None
    test_embed_config: EmbedConfig | None
    xtest_embed_config: EmbedConfig | None


@dataclass(frozen=True)
class FallibleFirstPartyPkgDigest:
    """The source files for a Go package, but fallible if embed preparation failed."""

    pkg_digest: FirstPartyPkgDigest | None
    exit_code: int = 0
    stderr: str | None = None


@dataclass(frozen=True)
class FirstPartyPkgDigestRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str:
        return self.address.spec


@rule
async def compute_first_party_package_import_path(
    request: FirstPartyPkgImportPathRequest,
) -> FirstPartyPkgImportPath:
    owning_go_mod = await Get(OwningGoMod, OwningGoModRequest(request.address))

    # We validate that the sources are for the target's directory, e.g. don't use `**`, so we can
    # simply look at the address to get the subpath.
    dir_path_rel_to_gomod = fast_relpath(request.address.spec_path, owning_go_mod.address.spec_path)

    go_mod_info = await Get(GoModInfo, GoModInfoRequest(owning_go_mod.address))
    import_path = (
        f"{go_mod_info.import_path}/{dir_path_rel_to_gomod}"
        if dir_path_rel_to_gomod
        else go_mod_info.import_path
    )
    return FirstPartyPkgImportPath(import_path, dir_path_rel_to_gomod)


@rule
async def analyze_first_party_package(
    request: FirstPartyPkgAnalysisRequest, analyzer: PackageAnalyzerSetup
) -> FallibleFirstPartyPkgAnalysis:
    wrapped_target, import_path_info, owning_go_mod = await MultiGet(
        Get(
            WrappedTarget,
            WrappedTargetRequest(
                request.address, description_of_origin="<first party pkg analysis>"
            ),
        ),
        Get(FirstPartyPkgImportPath, FirstPartyPkgImportPathRequest(request.address)),
        Get(OwningGoMod, OwningGoModRequest(request.address)),
    )
    go_mod_info = await Get(GoModInfo, GoModInfoRequest(owning_go_mod.address))

    pkg_sources = await Get(
        HydratedSources,
        HydrateSourcesRequest(wrapped_target.target[GoPackageSourcesField]),
    )

    input_digest = await Get(Digest, MergeDigests([pkg_sources.snapshot.digest, analyzer.digest]))
    result = await Get(
        FallibleProcessResult,
        Process(
            (analyzer.path, request.address.spec_path or "."),
            input_digest=input_digest,
            description=f"Determine metadata for {request.address}",
            level=LogLevel.DEBUG,
            env={"CGO_ENABLED": "0"},
        ),
    )
    return FallibleFirstPartyPkgAnalysis.from_process_result(
        result,
        dir_path=request.address.spec_path,
        import_path=import_path_info.import_path,
        minimum_go_version=go_mod_info.minimum_go_version or "",
        description_of_source=f"first-party Go package `{request.address}`",
    )


@rule
async def setup_first_party_pkg_digest(
    request: FirstPartyPkgDigestRequest,
) -> FallibleFirstPartyPkgDigest:
    embedder, wrapped_target, maybe_analysis = await MultiGet(
        Get(LoadedGoBinary, LoadedGoBinaryRequest("embedcfg", ("main.go",), "./embedder")),
        Get(
            WrappedTarget,
            WrappedTargetRequest(
                request.address, description_of_origin="<first party digest setup>"
            ),
        ),
        Get(FallibleFirstPartyPkgAnalysis, FirstPartyPkgAnalysisRequest(request.address)),
    )
    if maybe_analysis.analysis is None:
        return FallibleFirstPartyPkgDigest(
            pkg_digest=None, exit_code=maybe_analysis.exit_code, stderr=maybe_analysis.stderr
        )
    analysis = maybe_analysis.analysis

    tgt = wrapped_target.target
    pkg_sources = await Get(HydratedSources, HydrateSourcesRequest(tgt[GoPackageSourcesField]))
    sources_digest = pkg_sources.snapshot.digest

    embed_config = None
    test_embed_config = None
    xtest_embed_config = None

    # TODO(#13795): Error if you depend on resources without corresponding embed patterns?
    if analysis.embed_patterns or analysis.test_embed_patterns or analysis.xtest_embed_patterns:
        dependencies = await Get(Targets, DependenciesRequest(tgt[Dependencies]))
        resources_sources = await Get(
            SourceFiles,
            SourceFilesRequest(
                (
                    t.get(SourcesField)
                    for t in dependencies
                    # You can only embed resources located at or below the directory of the
                    # `go_package`. This is a restriction from Go.
                    # TODO(#13795): Error if you depend on resources above the go_package?
                    if t.address.spec_path.startswith(request.address.spec_path)
                ),
                for_sources_types=(ResourceSourceField,),
                # TODO: Switch to True. We need to be confident though that the generated files
                #  are located below the go_package.
                enable_codegen=False,
            ),
        )
        resources_digest = await Get(
            Digest, RemovePrefix(resources_sources.snapshot.digest, request.address.spec_path)
        )
        resources_digest = await Get(Digest, AddPrefix(resources_digest, "__resources__"))

        patterns_json = json.dumps(
            {
                "EmbedPatterns": analysis.embed_patterns,
                "TestEmbedPatterns": analysis.test_embed_patterns,
                "XTestEmbedPatterns": analysis.xtest_embed_patterns,
            }
        ).encode("utf-8")
        sources_digest, patterns_json_digest = await MultiGet(
            Get(Digest, MergeDigests((sources_digest, resources_digest))),
            Get(Digest, CreateDigest([FileContent("patterns.json", patterns_json)])),
        )
        input_digest = await Get(
            Digest, MergeDigests((sources_digest, patterns_json_digest, embedder.digest))
        )

        embed_result = await Get(
            FallibleProcessResult,
            Process(
                ("./embedder", "patterns.json", "__resources__"),
                input_digest=input_digest,
                description=f"Create embed mapping for {request.address}",
                level=LogLevel.DEBUG,
            ),
        )
        if embed_result.exit_code != 0:
            return FallibleFirstPartyPkgDigest(
                pkg_digest=None,
                exit_code=embed_result.exit_code,
                stderr=embed_result.stdout.decode("utf-8"),
            )
        metadata = json.loads(embed_result.stdout)
        embed_config = EmbedConfig.from_json_dict(metadata.get("EmbedConfig", {}))
        test_embed_config = EmbedConfig.from_json_dict(metadata.get("TestEmbedConfig", {}))
        xtest_embed_config = EmbedConfig.from_json_dict(metadata.get("XTestEmbedConfig", {}))

    return FallibleFirstPartyPkgDigest(
        FirstPartyPkgDigest(
            sources_digest,
            embed_config=embed_config,
            test_embed_config=test_embed_config,
            xtest_embed_config=xtest_embed_config,
        )
    )


def rules():
    return (*collect_rules(), *source_files.rules(), *load_go_binary.rules(), *pkg_analyzer.rules())
