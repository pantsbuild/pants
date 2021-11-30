# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import pkgutil
from dataclasses import dataclass
from typing import ClassVar

from pants.backend.go.target_types import GoPackageSourcesField
from pants.backend.go.util_rules.build_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.build_graph.address import Address
from pants.core.target_types import ResourcesGeneratingSourcesField, ResourceSourceField
from pants.engine.addresses import Addresses
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Targets,
    WrappedTarget,
)
from pants.util.dirutil import fast_relpath
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirstPartyPkgImportPath:
    """The derived import path of a first party package, based on its owning go.mod.

    Use `FirstPartyPkgInfo` instead for more detailed information like parsed imports.
    """

    import_path: str
    dir_path_rel_to_gomod: str


@dataclass(frozen=True)
class FirstPartyPkgImportPathRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str:
        return self.address.spec


@dataclass(frozen=True)
class FirstPartyPkgInfo:
    """All the info and digest needed to build a first-party Go package.

    The digest does not strip its source files; `dir_path` is relative to the build root.

    Use `FirstPartyPkgImportPath` if you only need the derived import path.
    """

    digest: Digest
    dir_path: str

    import_path: str

    imports: tuple[str, ...]
    test_imports: tuple[str, ...]
    xtest_imports: tuple[str, ...]

    go_files: tuple[str, ...]
    test_files: tuple[str, ...]
    xtest_files: tuple[str, ...]

    s_files: tuple[str, ...]

    minimum_go_version: str | None

    embed_patterns: tuple[str, ...]
    embed_config: EmbedConfig | None
    test_embed_patterns: tuple[str, ...]
    test_embed_config: EmbedConfig | None
    xtest_embed_patterns: tuple[str, ...]
    xtest_embed_config: EmbedConfig | None


@dataclass(frozen=True)
class FallibleFirstPartyPkgInfo:
    """Info needed to build a first-party Go package, but fallible if `go list` failed."""

    info: FirstPartyPkgInfo | None
    import_path: str
    exit_code: int = 0
    stderr: str | None = None


@dataclass(frozen=True)
class FirstPartyPkgInfoRequest(EngineAwareParameter):
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


@dataclass(frozen=True)
class PackageAnalyzerSetup:
    digest: Digest
    PATH: ClassVar[str] = "./_analyze_package"


@rule
async def compute_first_party_package_info(
    request: FirstPartyPkgInfoRequest, analyzer: PackageAnalyzerSetup
) -> FallibleFirstPartyPkgInfo:
    owning_go_mod = await Get(OwningGoMod, OwningGoModRequest(request.address))
    wrapped_target, import_path_info, go_mod_info = await MultiGet(
        Get(WrappedTarget, Address, request.address),
        Get(FirstPartyPkgImportPath, FirstPartyPkgImportPathRequest(request.address)),
        Get(GoModInfo, GoModInfoRequest(owning_go_mod.address)),
    )
    target = wrapped_target.target

    # Find resource targets.
    # TODO: This uses ExplicitlyProvidedDependencies to avoid triggering dependency inference which
    # causes a rule cycle back to this rule as dependency inference tries to analyze dependent
    # `go_package` targets. There really needs to be a way to limit `DependenciesRequest` to just
    # targets meeting certain criteria, which would be resource targets in this case.
    explicit_deps = await Get(
        ExplicitlyProvidedDependencies, DependenciesRequest(target[Dependencies])
    )
    explicit_deps_targets = await Get(Targets, Addresses(explicit_deps.includes))
    print(f"explicit_deps_targets={explicit_deps_targets}")
    pkg_relative_resource_targets = [
        tgt
        for tgt in explicit_deps_targets
        # Note: target expansion is not ocurring?
        if tgt.has_field(ResourceSourceField) or tgt.has_field(ResourcesGeneratingSourcesField)
        # TODO: Currently limited to resources directly under package in source tree. Allow any resource and
        # have paths be relative to the resources' spec_path.
        and tgt.address.spec_path.startswith(request.address.spec_path)
    ]
    print(f"pkg_relative_resource_targets={pkg_relative_resource_targets}")

    pkg_sources = await Get(
        HydratedSources,
        HydrateSourcesRequest(target[GoPackageSourcesField]),
    )

    resources_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                tgt[SourcesField],
                for_sources_types=(
                    ResourceSourceField,
                    ResourcesGeneratingSourcesField,
                ),
                enable_codegen=True,
            ),
        )
        for tgt in pkg_relative_resource_targets
    )

    original_resources_digest = await Get(
        Digest, MergeDigests([src.snapshot.digest for src in resources_sources])
    )
    stripped_resources_digest = await Get(
        Digest, RemovePrefix(original_resources_digest, request.address.spec_path)
    )
    resources_digest = await Get(Digest, AddPrefix(stripped_resources_digest, "__resources__"))
    ss = await Get(Snapshot, Digest, resources_digest)
    print(f"ss.files={ss.files}")

    sources_digest = await Get(
        Digest,
        MergeDigests([pkg_sources.snapshot.digest, resources_digest]),
    )

    input_digest = await Get(
        Digest,
        MergeDigests([sources_digest, analyzer.digest]),
    )

    result = await Get(
        FallibleProcessResult,
        Process(
            (analyzer.PATH, request.address.spec_path or "."),
            input_digest=input_digest,
            description=f"Determine metadata for {request.address}",
            level=LogLevel.DEBUG,
        ),
    )
    if result.exit_code != 0:
        return FallibleFirstPartyPkgInfo(
            info=None,
            import_path=import_path_info.import_path,
            exit_code=result.exit_code,
            stderr=result.stderr.decode("utf-8"),
        )

    print(f"stdout:\n{result.stdout.decode()}\nstderr:\n{result.stderr.decode()}")
    metadata = json.loads(result.stdout)
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
        return FallibleFirstPartyPkgInfo(
            info=None, import_path=import_path_info.import_path, exit_code=1, stderr=error
        )

    if "CgoFiles" in metadata:
        raise NotImplementedError(
            f"The first-party package {request.address} includes `CgoFiles`, which Pants does "
            "not yet support. Please open a feature request at "
            "https://github.com/pantsbuild/pants/issues/new/choose so that we know to "
            "prioritize adding support."
        )

    info = FirstPartyPkgInfo(
        digest=sources_digest,
        dir_path=request.address.spec_path,
        import_path=import_path_info.import_path,
        imports=tuple(metadata.get("Imports", [])),
        test_imports=tuple(metadata.get("TestImports", [])),
        xtest_imports=tuple(metadata.get("XTestImports", [])),
        go_files=tuple(metadata.get("GoFiles", [])),
        test_files=tuple(metadata.get("TestGoFiles", [])),
        xtest_files=tuple(metadata.get("XTestGoFiles", [])),
        s_files=tuple(metadata.get("SFiles", [])),
        minimum_go_version=go_mod_info.minimum_go_version,
        embed_patterns=tuple(metadata.get("EmbedPatterns", [])),
        embed_config=EmbedConfig.from_json_dict(metadata.get("EmbedConfig", {})),
        test_embed_patterns=tuple(metadata.get("TestEmbedPatterns", [])),
        test_embed_config=EmbedConfig.from_json_dict(metadata.get("TestEmbedConfig", {})),
        xtest_embed_patterns=tuple(metadata.get("XTestEmbedPatterns", [])),
        xtest_embed_config=EmbedConfig.from_json_dict(metadata.get("XTestEmbedConfig", {})),
    )
    return FallibleFirstPartyPkgInfo(info, import_path_info.import_path)


@rule
async def setup_analyzer() -> PackageAnalyzerSetup:
    def get_file(filename: str) -> bytes:
        content = pkgutil.get_data("pants.backend.go.util_rules", filename)
        if not content:
            raise AssertionError(f"Unable to find resource for `{filename}`.")
        return content

    analyer_sources_content = [
        FileContent(filename, get_file(filename))
        for filename in ("analyze_package.go", "read.go", "embedcfg.go")
    ]

    source_digest, import_config = await MultiGet(
        Get(Digest, CreateDigest(analyer_sources_content)),
        Get(ImportConfig, ImportConfigRequest, ImportConfigRequest.stdlib_only()),
    )

    built_analyzer_pkg = await Get(
        BuiltGoPackage,
        BuildGoPackageRequest(
            import_path="main",
            dir_path="",
            digest=source_digest,
            go_file_names=tuple(fc.path for fc in analyer_sources_content),
            s_file_names=(),
            direct_dependencies=(),
            minimum_go_version=None,
        ),
    )
    main_pkg_a_file_path = built_analyzer_pkg.import_paths_to_pkg_a_files["main"]
    input_digest = await Get(
        Digest, MergeDigests([built_analyzer_pkg.digest, import_config.digest])
    )

    analyzer = await Get(
        LinkedGoBinary,
        LinkGoBinaryRequest(
            input_digest=input_digest,
            archives=(main_pkg_a_file_path,),
            import_config_path=import_config.CONFIG_PATH,
            output_filename=PackageAnalyzerSetup.PATH,
            description="Link Go package analyzer",
        ),
    )

    return PackageAnalyzerSetup(analyzer.digest)


def rules():
    return collect_rules()
