# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Building third-party Go packages addressed by import path.

Used under `[golang].third_party_target_granularity = "module"`: module targets carry no
inter-module edges (Go module graphs may contain cycles), so dependencies resolve against
the per-`go.mod` package index instead of via target edges.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from pants.backend.go.util_rules import build_pkg_stdlib
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    FallibleBuildGoPackageRequest,
)
from pants.backend.go.util_rules.build_pkg_stdlib import (
    BuildGoPackageRequestForStdlibRequest,
    setup_build_go_package_target_request_for_stdlib,
)
from pants.backend.go.util_rules.go_mod import GoModInfoRequest, determine_go_mod_info
from pants.backend.go.util_rules.import_analysis import (
    GoStdLibPackagesRequest,
    analyze_go_stdlib_packages,
)
from pants.backend.go.util_rules.pkg_pattern import match_simple_pattern
from pants.backend.go.util_rules.third_party_pkg import (
    AllThirdPartyPackagesRequest,
    download_and_analyze_third_party_packages,
    resolve_third_party_pkg_sources_digest,
)
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.selectors import concurrently
from pants.engine.rules import collect_rules, implicitly, rule


@dataclass(frozen=True)
class BuildGoPackageRequestForThirdPartyPackageRequest(EngineAwareParameter):
    """Build a third-party package and its dependencies, identified by import path."""

    import_path: str
    go_mod_address: Address
    build_opts: GoBuildOptions
    is_main: bool = False

    def debug_hint(self) -> str:
        return self.import_path


@rule
async def setup_build_go_package_target_request_for_third_party(
    request: BuildGoPackageRequestForThirdPartyPackageRequest,
) -> FallibleBuildGoPackageRequest:
    go_mod_info = await determine_go_mod_info(GoModInfoRequest(request.go_mod_address))
    all_packages = await download_and_analyze_third_party_packages(
        AllThirdPartyPackagesRequest(
            request.go_mod_address,
            go_mod_info.digest,
            go_mod_info.mod_path,
            build_opts=request.build_opts,
        )
    )
    pkg_info = all_packages.import_paths_to_pkg_info.get(request.import_path)
    if pkg_info is None:
        return FallibleBuildGoPackageRequest(
            None,
            request.import_path,
            exit_code=1,
            stderr=(
                f"Unable to find third-party package for import path `{request.import_path}` "
                f"among the modules of `{go_mod_info.mod_path}`."
            ),
        )

    # We error if trying to _build_ a package with issues (vs. only generating the target and
    # using in project introspection).
    if pkg_info.error:
        raise pkg_info.error

    digest = await resolve_third_party_pkg_sources_digest(pkg_info)

    imports = set(pkg_info.imports)
    # Add implicit dependencies for Cgo generated code.
    if pkg_info.cgo_files:
        imports.update(["runtime/cgo", "syscall"])

    stdlib_packages = await analyze_go_stdlib_packages(
        GoStdLibPackagesRequest(
            with_race_detector=request.build_opts.with_race_detector,
            cgo_enabled=request.build_opts.cgo_enabled,
        )
    )

    third_party_dep_import_paths = []
    stdlib_dep_import_paths = []
    for dep_import_path in sorted(imports):
        if dep_import_path in {"builtin", "C", "unsafe"}:
            continue
        if dep_import_path in all_packages.import_paths_to_pkg_info:
            third_party_dep_import_paths.append(dep_import_path)
        elif dep_import_path in stdlib_packages:
            stdlib_dep_import_paths.append(dep_import_path)

    maybe_third_party_direct_dependencies = await concurrently(
        setup_build_go_package_target_request_for_third_party(
            BuildGoPackageRequestForThirdPartyPackageRequest(
                import_path=dep_import_path,
                go_mod_address=request.go_mod_address,
                build_opts=request.build_opts,
            )
        )
        for dep_import_path in third_party_dep_import_paths
    )
    stdlib_direct_dependencies = await concurrently(
        setup_build_go_package_target_request_for_stdlib(
            BuildGoPackageRequestForStdlibRequest(
                import_path=dep_import_path,
                build_opts=request.build_opts,
            ),
            **implicitly(),
        )
        for dep_import_path in stdlib_dep_import_paths
    )

    direct_dependencies = []
    for maybe_dep in maybe_third_party_direct_dependencies:
        if maybe_dep.request is None:
            return dataclasses.replace(maybe_dep, dependency_failed=True)
        direct_dependencies.append(maybe_dep.request)
    for stdlib_dep in stdlib_direct_dependencies:
        assert stdlib_dep.request is not None
        direct_dependencies.append(stdlib_dep.request)

    with_coverage = False
    coverage_config = request.build_opts.coverage_config
    if coverage_config:
        for pattern in coverage_config.import_path_include_patterns:
            with_coverage = with_coverage or match_simple_pattern(pattern)(request.import_path)

    result = BuildGoPackageRequest(
        digest=digest,
        import_path="main" if request.is_main else request.import_path,
        pkg_name=pkg_info.name,
        dir_path=pkg_info.dir_path,
        build_opts=request.build_opts,
        go_files=pkg_info.go_files,
        s_files=pkg_info.s_files,
        cgo_files=pkg_info.cgo_files,
        cgo_flags=pkg_info.cgo_flags,
        c_files=pkg_info.c_files,
        header_files=pkg_info.h_files,
        cxx_files=pkg_info.cxx_files,
        objc_files=pkg_info.m_files,
        fortran_files=pkg_info.f_files,
        prebuilt_object_files=pkg_info.syso_files,
        minimum_go_version=pkg_info.minimum_go_version,
        direct_dependencies=tuple(sorted(direct_dependencies, key=lambda p: p.import_path)),
        embed_config=pkg_info.embed_config,
        with_coverage=with_coverage,
    )
    return FallibleBuildGoPackageRequest(result, request.import_path)


def rules():
    return (
        *collect_rules(),
        *build_pkg_stdlib.rules(),
    )
