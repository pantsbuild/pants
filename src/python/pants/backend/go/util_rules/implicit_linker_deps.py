# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.go.util_rules.build_pkg import BuiltGoPackage
from pants.backend.go.util_rules.build_pkg_target import BuildGoPackageRequestForStdlibRequest
from pants.backend.go.util_rules.link_defs import (
    ImplicitLinkerDependencies,
    ImplicitLinkerDependenciesHook,
)
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict


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

    built_implicit_linker_deps = await MultiGet(
        Get(
            BuiltGoPackage,
            BuildGoPackageRequestForStdlibRequest(dep_import_path, build_opts=request.build_opts),
        )
        for dep_import_path in implicit_deps_import_paths
    )

    implicit_dep_digests = []
    import_paths_to_pkg_a_files: dict[str, str] = {}
    for built_implicit_linker_dep in built_implicit_linker_deps:
        import_paths_to_pkg_a_files.update(built_implicit_linker_dep.import_paths_to_pkg_a_files)
        implicit_dep_digests.append(built_implicit_linker_dep.digest)

    digest = await Get(Digest, MergeDigests(implicit_dep_digests))

    return ImplicitLinkerDependencies(
        digest=digest,
        import_paths_to_pkg_a_files=FrozenDict(import_paths_to_pkg_a_files),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(ImplicitLinkerDependenciesHook, SdkImplicitLinkerDependenciesHook),
    )
