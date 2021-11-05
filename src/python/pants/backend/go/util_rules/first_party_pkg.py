# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
import pkgutil
from dataclasses import dataclass
from typing import ClassVar

from pants.backend.go.target_types import (
    GoFirstPartyPackageSourcesField,
    GoFirstPartyPackageSubpathField,
    GoImportPathField,
)
from pants.backend.go.util_rules.build_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest, WrappedTarget
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirstPartyPkgInfo:
    """All the info and digest needed to build a first-party Go package.

    The digest does not strip its source files. You must set `working_dir` appropriately to use the
    `go_first_party_package` target's `subpath` field.
    """

    digest: Digest
    subpath: str

    import_path: str

    imports: tuple[str, ...]
    test_imports: tuple[str, ...]
    xtest_imports: tuple[str, ...]

    go_files: tuple[str, ...]
    test_files: tuple[str, ...]
    xtest_files: tuple[str, ...]

    s_files: tuple[str, ...]


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


@dataclass(frozen=True)
class PackageAnalyzerSetup:
    digest: Digest
    PATH: ClassVar[str] = "./_analyze_package"


@rule
async def compute_first_party_package_info(
    request: FirstPartyPkgInfoRequest, analyzer: PackageAnalyzerSetup
) -> FallibleFirstPartyPkgInfo:
    go_mod_address = request.address.maybe_convert_to_target_generator()
    wrapped_target, go_mod_info = await MultiGet(
        Get(WrappedTarget, Address, request.address),
        Get(GoModInfo, GoModInfoRequest(go_mod_address)),
    )
    target = wrapped_target.target
    import_path = target[GoImportPathField].value
    subpath = target[GoFirstPartyPackageSubpathField].value

    pkg_sources = await Get(
        HydratedSources, HydrateSourcesRequest(target[GoFirstPartyPackageSourcesField])
    )
    input_digest = await Get(
        Digest,
        MergeDigests([pkg_sources.snapshot.digest, analyzer.digest]),
    )
    path = request.address.spec_path if request.address.spec_path else "."
    path = os.path.join(path, subpath) if subpath else path
    if not path:
        path = "."
    result = await Get(
        FallibleProcessResult,
        Process(
            (analyzer.PATH, path),
            input_digest=input_digest,
            description=f"Determine metadata for {request.address}",
            level=LogLevel.DEBUG,
        ),
    )
    if result.exit_code != 0:
        return FallibleFirstPartyPkgInfo(
            info=None,
            import_path=import_path,
            exit_code=result.exit_code,
            stderr=result.stderr.decode("utf-8"),
        )

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
            info=None, import_path=import_path, exit_code=1, stderr=error
        )

    if "CgoFiles" in metadata:
        raise NotImplementedError(
            f"The first-party package {request.address} includes `CgoFiles`, which Pants does "
            "not yet support. Please open a feature request at "
            "https://github.com/pantsbuild/pants/issues/new/choose so that we know to "
            "prioritize adding support."
        )

    info = FirstPartyPkgInfo(
        digest=pkg_sources.snapshot.digest,
        subpath=os.path.join(target.address.spec_path, subpath),
        import_path=import_path,
        imports=tuple(metadata.get("Imports", [])),
        test_imports=tuple(metadata.get("TestImports", [])),
        xtest_imports=tuple(metadata.get("XTestImports", [])),
        go_files=tuple(metadata.get("GoFiles", [])),
        test_files=tuple(metadata.get("TestGoFiles", [])),
        xtest_files=tuple(metadata.get("XTestGoFiles", [])),
        s_files=tuple(metadata.get("SFiles", [])),
    )
    return FallibleFirstPartyPkgInfo(info, import_path)


@rule
async def setup_analyzer() -> PackageAnalyzerSetup:
    source_entry_content = pkgutil.get_data("pants.backend.go.util_rules", "analyze_package.go")
    if not source_entry_content:
        raise AssertionError("Unable to find resource for `analyze_package.go`.")

    source_entry = FileContent("analyze_package.go", source_entry_content)

    source_digest, import_config = await MultiGet(
        Get(Digest, CreateDigest([source_entry])),
        Get(ImportConfig, ImportConfigRequest, ImportConfigRequest.stdlib_only()),
    )

    built_analyzer_pkg = await Get(
        BuiltGoPackage,
        BuildGoPackageRequest(
            import_path="main",
            subpath="",
            digest=source_digest,
            go_file_names=(source_entry.path,),
            s_file_names=(),
            direct_dependencies=(),
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
