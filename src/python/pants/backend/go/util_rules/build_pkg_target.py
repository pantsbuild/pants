# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import ClassVar, Type, cast

from pants.backend.go.target_types import (
    GoImportPathField,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
)
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    FallibleBuildGoPackageRequest,
)
from pants.backend.go.util_rules.coverage import GoCoverageConfig
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FallibleFirstPartyPkgDigest,
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgDigestRequest,
)
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.third_party_pkg import (
    ThirdPartyPkgAnalysis,
    ThirdPartyPkgAnalysisRequest,
)
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.graph import AmbiguousCodegenImplementationsException
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    SourcesField,
    Target,
    Targets,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionMembership, union
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import bullet_list


@dataclass(frozen=True)
class BuildGoPackageTargetRequest(EngineAwareParameter):
    """Build a `go_package`, `go_third_party_package`, or Go codegen target and its dependencies as
    `__pkg__.a` files."""

    address: Address
    is_main: bool = False
    for_tests: bool = False
    coverage_config: GoCoverageConfig | None = None

    def debug_hint(self) -> str:
        return str(self.address)


@union
@dataclass(frozen=True)
class GoCodegenBuildRequest:
    """The plugin hook to build/compile Go code.

    Note that you should still use the normal `GenerateSourcesRequest` plugin hook from
    `pants.engine.target` too, which is necessary for integrations like the `export-codegen` goal.
    However, that is only helpful to generate the raw `.go` files; you also need to use this
    plugin hook so that Pants knows how to compile those generated `.go` files.

    Subclass this and set the class property `generate_from`. Define a rule that goes from your
    subclass to `BuildGoPackageRequest` - the request must result in valid compilation, which you
    should test for by using `rule_runner.request(BuiltGoPackage, BuildGoPackageRequest)` in your
    tests. For example, make sure to set up any third-party packages needed by the generated code.
    Finally, register `UnionRule(GoCodegenBuildRequest, MySubclass)`.
    """

    target: Target

    generate_from: ClassVar[type[SourcesField]]


def maybe_get_codegen_request_type(
    tgt: Target, union_membership: UnionMembership
) -> GoCodegenBuildRequest | None:
    if not tgt.has_field(SourcesField):
        return None
    generate_request_types = cast(
        FrozenOrderedSet[Type[GoCodegenBuildRequest]], union_membership.get(GoCodegenBuildRequest)
    )
    sources_field = tgt[SourcesField]
    relevant_requests = [
        req for req in generate_request_types if isinstance(sources_field, req.generate_from)
    ]
    if len(relevant_requests) > 1:
        generate_from_sources = relevant_requests[0].generate_from.__name__
        raise AmbiguousCodegenImplementationsException(
            f"Multiple registered code generators from {GoCodegenBuildRequest.__name__} can "
            f"generate from {generate_from_sources}. It is ambiguous which implementation to "
            f"use.\n\n"
            f"Possible implementations:\n\n"
            f"{bullet_list(sorted(generator.__name__ for generator in relevant_requests))}"
        )
    return relevant_requests[0](tgt) if relevant_requests else None


# NB: We must have a description for the streaming of this rule to work properly
# (triggered by `FallibleBuildGoPackageRequest` subclassing `EngineAwareReturnType`).
@rule(desc="Set up Go compilation request", level=LogLevel.DEBUG)
async def setup_build_go_package_target_request(
    request: BuildGoPackageTargetRequest, union_membership: UnionMembership
) -> FallibleBuildGoPackageRequest:
    wrapped_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(request.address, description_of_origin="<build_pkg_target.py>"),
    )
    target = wrapped_target.target

    codegen_request = maybe_get_codegen_request_type(target, union_membership)
    if codegen_request:
        codegen_result = await Get(
            FallibleBuildGoPackageRequest, GoCodegenBuildRequest, codegen_request
        )
        return codegen_result

    embed_config: EmbedConfig | None = None
    if target.has_field(GoPackageSourcesField):
        _maybe_first_party_pkg_analysis, _maybe_first_party_pkg_digest = await MultiGet(
            Get(FallibleFirstPartyPkgAnalysis, FirstPartyPkgAnalysisRequest(target.address)),
            Get(FallibleFirstPartyPkgDigest, FirstPartyPkgDigestRequest(target.address)),
        )
        if _maybe_first_party_pkg_analysis.analysis is None:
            return FallibleBuildGoPackageRequest(
                None,
                _maybe_first_party_pkg_analysis.import_path,
                exit_code=_maybe_first_party_pkg_analysis.exit_code,
                stderr=_maybe_first_party_pkg_analysis.stderr,
            )
        if _maybe_first_party_pkg_digest.pkg_digest is None:
            return FallibleBuildGoPackageRequest(
                None,
                _maybe_first_party_pkg_analysis.import_path,
                exit_code=_maybe_first_party_pkg_digest.exit_code,
                stderr=_maybe_first_party_pkg_digest.stderr,
            )
        _first_party_pkg_analysis = _maybe_first_party_pkg_analysis.analysis
        _first_party_pkg_digest = _maybe_first_party_pkg_digest.pkg_digest

        digest = _first_party_pkg_digest.digest
        import_path = _first_party_pkg_analysis.import_path
        dir_path = _first_party_pkg_analysis.dir_path
        minimum_go_version = _first_party_pkg_analysis.minimum_go_version

        go_file_names = _first_party_pkg_analysis.go_files
        embed_config = _first_party_pkg_digest.embed_config
        if request.for_tests:
            # TODO: Build the test sources separately and link the two object files into the
            #  package archive?
            # TODO: The `go` tool changes the displayed import path for the package when it has
            #  test files. Do we need to do something similar?
            go_file_names += _first_party_pkg_analysis.test_go_files
            if _first_party_pkg_digest.test_embed_config:
                if embed_config:
                    embed_config = embed_config.merge(_first_party_pkg_digest.test_embed_config)
                else:
                    embed_config = _first_party_pkg_digest.test_embed_config
        s_file_names = _first_party_pkg_analysis.s_files

    elif target.has_field(GoThirdPartyPackageDependenciesField):
        import_path = target[GoImportPathField].value

        _go_mod_address = target.address.maybe_convert_to_target_generator()
        _go_mod_info = await Get(GoModInfo, GoModInfoRequest(_go_mod_address))
        _third_party_pkg_info = await Get(
            ThirdPartyPkgAnalysis,
            ThirdPartyPkgAnalysisRequest(import_path, _go_mod_info.digest, _go_mod_info.mod_path),
        )

        # We error if trying to _build_ a package with issues (vs. only generating the target and
        # using in project introspection).
        if _third_party_pkg_info.error:
            raise _third_party_pkg_info.error

        dir_path = _third_party_pkg_info.dir_path
        digest = _third_party_pkg_info.digest
        minimum_go_version = _third_party_pkg_info.minimum_go_version
        go_file_names = _third_party_pkg_info.go_files
        s_file_names = _third_party_pkg_info.s_files
        embed_config = _third_party_pkg_info.embed_config

    else:
        raise AssertionError(
            f"Unknown how to build `{target.alias}` target at address {request.address} with Go. "
            "Please open a bug at https://github.com/pantsbuild/pants/issues/new/choose with this "
            "message!"
        )

    all_deps = await Get(Targets, DependenciesRequest(target[Dependencies]))
    maybe_direct_dependencies = await MultiGet(
        Get(FallibleBuildGoPackageRequest, BuildGoPackageTargetRequest(tgt.address))
        for tgt in all_deps
        if (
            tgt.has_field(GoPackageSourcesField)
            or tgt.has_field(GoThirdPartyPackageDependenciesField)
            or bool(maybe_get_codegen_request_type(tgt, union_membership))
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
        dir_path=dir_path,
        go_file_names=go_file_names,
        s_file_names=s_file_names,
        minimum_go_version=minimum_go_version,
        direct_dependencies=tuple(direct_dependencies),
        for_tests=request.for_tests,
        embed_config=embed_config,
        coverage_config=request.coverage_config,
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
