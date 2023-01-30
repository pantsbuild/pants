# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

import ijson.backends.python as ijson

from pants.backend.go.dependency_inference import (
    GoImportPathsMappingAddressSet,
    GoModuleImportPathsMapping,
    GoModuleImportPathsMappings,
    GoModuleImportPathsMappingsHook,
)
from pants.backend.go.target_types import DEFAULT_GO_SDK_ADDR
from pants.backend.go.util_rules import go_mod
from pants.backend.go.util_rules.cgo import CGoCompilerFlags
from pants.backend.go.util_rules.go_mod import AllGoModTargets
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoStdLibPackage:
    name: str
    import_path: str
    pkg_source_path: str
    pkg_target: str  # Note: This will be removed once PRs land to support building the Go SDK.
    imports: tuple[str, ...]
    import_map: FrozenDict[str, str]

    # Analysis for when Pants is able to compile the SDK directly.
    go_files: tuple[str, ...]
    cgo_files: tuple[str, ...]
    c_files: tuple[str, ...]
    cxx_files: tuple[str, ...]
    m_files: tuple[str, ...]
    h_files: tuple[str, ...]
    f_files: tuple[str, ...]
    s_files: tuple[str, ...]
    syso_files: tuple[str, ...]
    cgo_flags: CGoCompilerFlags


class GoStdLibPackages(FrozenDict[str, GoStdLibPackage]):
    """A mapping of standard library import paths to an analysis of the package at that import
    path."""


@dataclass(frozen=True)
class GoStdLibPackagesRequest:
    with_race_detector: bool
    cgo_enabled: bool = True


@rule(desc="Analyze Go standard library packages.", level=LogLevel.DEBUG)
async def analyze_go_stdlib_packages(request: GoStdLibPackagesRequest) -> GoStdLibPackages:
    maybe_race_arg = ["-race"] if request.with_race_detector else []
    list_result = await Get(
        ProcessResult,
        GoSdkProcess(
            # "-find" skips determining dependencies and imports for each package.
            command=("list", *maybe_race_arg, "-json", "std"),
            env={"CGO_ENABLED": "1" if request.cgo_enabled else "0"},
            description="Ask Go for its available import paths",
        ),
    )
    stdlib_packages = {}
    for pkg_json in ijson.items(list_result.stdout, "", multiple_values=True):
        import_path = pkg_json.get("ImportPath")
        pkg_source_path = pkg_json.get("Dir")
        pkg_target = pkg_json.get("Target")

        if not import_path or not pkg_source_path or not pkg_target:
            continue

        stdlib_packages[import_path] = GoStdLibPackage(
            name=pkg_json.get("Name"),
            import_path=import_path,
            pkg_source_path=pkg_source_path,
            pkg_target=pkg_target,
            imports=tuple(pkg_json.get("Imports", ())),
            import_map=FrozenDict(pkg_json.get("ImportMap", {})),
            go_files=tuple(pkg_json.get("GoFiles", ())),
            cgo_files=tuple(pkg_json.get("CgoFiles", ())),
            c_files=tuple(pkg_json.get("CFiles", ())),
            cxx_files=tuple(pkg_json.get("CXXFiles", ())),
            m_files=tuple(pkg_json.get("MFiles", ())),
            h_files=tuple(pkg_json.get("HFiles", ())),
            f_files=tuple(pkg_json.get("FFiles", ())),
            s_files=tuple(pkg_json.get("SFiles", ())),
            syso_files=tuple(pkg_json.get("SysoFiles", ())),
            cgo_flags=CGoCompilerFlags(
                cflags=tuple(pkg_json.get("CgoCFLAGS", [])),
                cppflags=tuple(pkg_json.get("CgoCPPFLAGS", [])),
                cxxflags=tuple(pkg_json.get("CgoCXXFLAGS", [])),
                fflags=tuple(pkg_json.get("CgoFFLAGS", [])),
                ldflags=tuple(pkg_json.get("CgoLDFLAGS", [])),
                pkg_config=tuple(pkg_json.get("CgoPkgConfig", [])),
            ),
        )

    return GoStdLibPackages(stdlib_packages)


class GoSdkImportPathsMappingsHook(GoModuleImportPathsMappingsHook):
    pass


@rule(desc="Analyze and map Go import paths for the Go SDK.", level=LogLevel.DEBUG)
async def go_map_import_paths_by_module(
    _request: GoSdkImportPathsMappingsHook,
    all_go_mod_targets: AllGoModTargets,
) -> GoModuleImportPathsMappings:
    import_paths_by_module: dict[Address, dict[str, set[Address]]] = defaultdict(
        lambda: defaultdict(set)
    )

    stdlib_packages = await Get(
        GoStdLibPackages,
        GoStdLibPackagesRequest(with_race_detector=False),
    )

    # Replicate the Go SDK imports path to all Go modules.
    # TODO: This will need to change eventually for multiple Go SDK support.
    for import_path in stdlib_packages.keys():
        for go_mod_tgt in all_go_mod_targets:
            import_paths_by_module[go_mod_tgt.address][import_path].add(
                DEFAULT_GO_SDK_ADDR.create_generated(import_path)
            )

    return GoModuleImportPathsMappings(
        FrozenDict(
            {
                go_mod_addr: GoModuleImportPathsMapping(
                    mapping=FrozenDict(
                        {
                            import_path: GoImportPathsMappingAddressSet(
                                addresses=tuple(sorted(addresses)), infer_all=False
                            )
                            for import_path, addresses in import_path_mapping.items()
                        }
                    ),
                    address_to_import_path=FrozenDict(
                        {
                            address: import_path
                            for import_path, addresses in import_path_mapping.items()
                            for address in addresses
                        }
                    ),
                )
                for go_mod_addr, import_path_mapping in import_paths_by_module.items()
            }
        )
    )


def rules():
    return (
        *collect_rules(),
        *go_mod.rules(),
        UnionRule(GoModuleImportPathsMappingsHook, GoSdkImportPathsMappingsHook),
    )
