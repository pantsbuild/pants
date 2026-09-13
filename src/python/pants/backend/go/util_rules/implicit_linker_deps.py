# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.go.util_rules.build_pkg import (
    MergeBuiltGoPackageArchivesRequest,
    merge_built_go_package_archives,
    required_built_go_package,
)
from pants.backend.go.util_rules.build_pkg_stdlib import BuildGoPackageRequestForStdlibRequest
from pants.backend.go.util_rules.link_defs import (
    ImplicitLinkerDependencies,
    ImplicitLinkerDependenciesHook,
)
from pants.engine.internals.selectors import concurrently
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.unions import UnionRule


class SdkImplicitLinkerDependenciesHook(ImplicitLinkerDependenciesHook):
    pass


@rule
async def provide_sdk_implicit_linker_dependencies(
    request: SdkImplicitLinkerDependenciesHook,
) -> ImplicitLinkerDependencies:
    # Build implicit linker deps.
    # All binaries link to `runtime`.
    implicit_deps_import_paths: set[str] = {"runtime"}
    # TODO: External linking mode forces an import of runtime/cgo.
    # TODO: On ARM with GOARM=5, it forces an import of math, for soft floating point.
    if request.build_opts.with_race_detector:
        implicit_deps_import_paths.add("runtime/race")
    if request.build_opts.with_msan:
        implicit_deps_import_paths.add("runtime/msan")
    if request.build_opts.with_asan:
        implicit_deps_import_paths.add("runtime/asan")
    # TODO: Building for coverage in Go 1.20+ forces an import of runtime/coverage.

    built_implicit_linker_deps = await concurrently(
        required_built_go_package(
            **implicitly(
                BuildGoPackageRequestForStdlibRequest(
                    dep_import_path, build_opts=request.build_opts
                )
            ),
        )
        for dep_import_path in implicit_deps_import_paths
    )

    merged = await merge_built_go_package_archives(
        MergeBuiltGoPackageArchivesRequest(tuple(built_implicit_linker_deps))
    )

    return ImplicitLinkerDependencies(
        digest=merged.digest,
        import_paths_to_pkg_a_files=merged.import_paths_to_pkg_a_files,
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(ImplicitLinkerDependenciesHook, SdkImplicitLinkerDependenciesHook),
    )
