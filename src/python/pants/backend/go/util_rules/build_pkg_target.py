# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoFirstPartyPackageSourcesField,
    GoFirstPartyPackageSubpathField,
    GoImportPathField,
    GoThirdPartyPackageDependenciesField,
)
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    FallibleBuildGoPackageRequest,
)
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgInfo,
    FirstPartyPkgInfoRequest,
)
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.third_party_pkg import ThirdPartyPkgInfo, ThirdPartyPkgInfoRequest
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, UnexpandedTargets, WrappedTarget
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class BuildGoPackageTargetRequest(EngineAwareParameter):
    """Build a `go_first_party_package` or `go_third_party_package` target and its dependencies as
    `__pkg__.a` files."""

    address: Address
    is_main: bool = False
    for_tests: bool = False

    def debug_hint(self) -> str:
        return str(self.address)


# NB: We must have a description for the streaming of this rule to work properly
# (triggered by `FallibleBuildGoPackageRequest` subclassing `EngineAwareReturnType`).
@rule(desc="Set up Go compilation request", level=LogLevel.DEBUG)
async def setup_build_go_package_target_request(
    request: BuildGoPackageTargetRequest,
) -> FallibleBuildGoPackageRequest:
    wrapped_target = await Get(WrappedTarget, Address, request.address)
    target = wrapped_target.target
    import_path = target[GoImportPathField].value

    if target.has_field(GoFirstPartyPackageSourcesField):
        _maybe_first_party_pkg_info = await Get(
            FallibleFirstPartyPkgInfo, FirstPartyPkgInfoRequest(target.address)
        )
        if _maybe_first_party_pkg_info.info is None:
            return FallibleBuildGoPackageRequest(
                None,
                import_path,
                exit_code=_maybe_first_party_pkg_info.exit_code,
                stderr=_maybe_first_party_pkg_info.stderr,
            )
        _first_party_pkg_info = _maybe_first_party_pkg_info.info

        digest = _first_party_pkg_info.digest
        subpath = os.path.join(
            target.address.spec_path, target[GoFirstPartyPackageSubpathField].value
        )

        go_file_names = _first_party_pkg_info.go_files
        if request.for_tests:
            # TODO: Build the test sources separately and link the two object files into the package archive?
            # TODO: The `go` tool changes the displayed import path for the package when it has test files. Do we
            #   need to do something similar?
            go_file_names += _first_party_pkg_info.test_files
        s_file_names = _first_party_pkg_info.s_files

    elif target.has_field(GoThirdPartyPackageDependenciesField):
        _go_mod_address = target.address.maybe_convert_to_target_generator()
        _go_mod_info = await Get(GoModInfo, GoModInfoRequest(_go_mod_address))
        _third_party_pkg_info = await Get(
            ThirdPartyPkgInfo,
            ThirdPartyPkgInfoRequest(
                import_path=import_path, go_mod_stripped_digest=_go_mod_info.stripped_digest
            ),
        )

        # We error if trying to _build_ a package with issues (vs. only generating the target and
        # using in project introspection).
        if _third_party_pkg_info.error:
            raise _third_party_pkg_info.error

        subpath = _third_party_pkg_info.subpath
        digest = _third_party_pkg_info.digest
        go_file_names = _third_party_pkg_info.go_files
        s_file_names = _third_party_pkg_info.s_files

    else:
        raise AssertionError(
            f"Unknown how to build `{target.alias}` target at address {request.address} with Go."
            "Please open a bug at https://github.com/pantsbuild/pants/issues/new/choose with this "
            "message!"
        )

    # TODO: If you use `Targets` here, then we replace the direct dep on the `go_mod` with all
    #  of its generated targets...Figure this out.
    all_deps = await Get(UnexpandedTargets, DependenciesRequest(target[Dependencies]))
    maybe_direct_dependencies = await MultiGet(
        Get(FallibleBuildGoPackageRequest, BuildGoPackageTargetRequest(tgt.address))
        for tgt in all_deps
        if (
            tgt.has_field(GoFirstPartyPackageSourcesField)
            or tgt.has_field(GoThirdPartyPackageDependenciesField)
        )
    )
    direct_dependencies = []
    for maybe_dep in maybe_direct_dependencies:
        if maybe_dep.request is None:
            return dataclasses.replace(
                maybe_dep,
                import_path="main" if request.is_main else import_path,
                dependency_failed=True,
            )
        direct_dependencies.append(maybe_dep.request)

    result = BuildGoPackageRequest(
        digest=digest,
        import_path="main" if request.is_main else import_path,
        subpath=subpath,
        go_file_names=go_file_names,
        s_file_names=s_file_names,
        direct_dependencies=tuple(direct_dependencies),
        for_tests=request.for_tests,
    )
    return FallibleBuildGoPackageRequest(result, import_path)


@rule
def required_build_go_package_request(
    fallible_request: FallibleBuildGoPackageRequest,
) -> BuildGoPackageRequest:
    if fallible_request.request is not None:
        return fallible_request.request
    raise Exception(
        f"Failed to determine metadata to compile {fallible_request.import_path}:\n"
        f"{fallible_request.stderr}"
    )


def rules():
    return collect_rules()
