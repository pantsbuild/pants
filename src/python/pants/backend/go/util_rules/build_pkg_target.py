# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import ClassVar, Type, cast

from pants.backend.go.dependency_inference import GoModuleImportPathsMapping
from pants.backend.go.go_sources.load_go_binary import LoadedGoBinary, LoadedGoBinaryRequest
from pants.backend.go.target_type_rules import GoImportPathMappingRequest
from pants.backend.go.target_types import (
    GoAssemblerFlagsField,
    GoCompilerFlagsField,
    GoImportPathField,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
)
from pants.backend.go.util_rules import build_opts
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    FallibleBuildGoPackageRequest,
)
from pants.backend.go.util_rules.cgo import CGoCompilerFlags
from pants.backend.go.util_rules.coverage import GoCoverMode
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FallibleFirstPartyPkgDigest,
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgDigestRequest,
    FirstPartyPkgImportPath,
    FirstPartyPkgImportPathRequest,
)
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.import_analysis import (
    GoStdLibPackage,
    GoStdLibPackages,
    GoStdLibPackagesRequest,
)
from pants.backend.go.util_rules.pkg_pattern import match_simple_pattern
from pants.backend.go.util_rules.third_party_pkg import (
    ThirdPartyPkgAnalysis,
    ThirdPartyPkgAnalysisRequest,
)
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.environment import EnvironmentName
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.graph import AmbiguousCodegenImplementationsException
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process
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
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import bullet_list


@dataclass(frozen=True)
class BuildGoPackageTargetRequest(EngineAwareParameter):
    """Build a `go_package`, `go_third_party_package`, or Go codegen target and its dependencies as
    `__pkg__.a` files."""

    address: Address
    build_opts: GoBuildOptions
    is_main: bool = False
    for_tests: bool = False
    for_xtests: bool = False

    # If True, then force coverage instead of applying import path patterns from `build_opts.coverage_config`.
    with_coverage: bool = False

    # Extra standard library dependencies to force on the target. Useful for implicit linker dependencies.
    extra_stdlib_dependencies: tuple[str, ...] = ()

    def debug_hint(self) -> str:
        return str(self.address)

    def __post_init__(self):
        if self.for_tests and self.for_xtests:
            raise ValueError(
                "`BuildGoPackageTargetRequest.for_tests` and `BuildGoPackageTargetRequest.for_xtests` "
                "cannot be set together."
            )


@dataclass(frozen=True)
class BuildGoPackageRequestForStdlibRequest:
    import_path: str
    build_opts: GoBuildOptions


@union(in_scope_types=[EnvironmentName])
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
    build_opts: GoBuildOptions

    generate_from: ClassVar[type[SourcesField]]


def maybe_get_codegen_request_type(
    tgt: Target, build_opts: GoBuildOptions, union_membership: UnionMembership
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
    return relevant_requests[0](tgt, build_opts) if relevant_requests else None


# NB: We must have a description for the streaming of this rule to work properly
# (triggered by `FallibleBuildGoPackageRequest` subclassing `EngineAwareReturnType`).
@rule(desc="Set up Go compilation request", level=LogLevel.DEBUG)
async def setup_build_go_package_target_request(
    request: BuildGoPackageTargetRequest,
    union_membership: UnionMembership,
    goroot: GoRoot,
) -> FallibleBuildGoPackageRequest:
    wrapped_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(request.address, description_of_origin="<build_pkg_target.py>"),
    )
    target = wrapped_target.target

    codegen_request = maybe_get_codegen_request_type(target, request.build_opts, union_membership)
    if codegen_request:
        codegen_result = await Get(
            FallibleBuildGoPackageRequest, GoCodegenBuildRequest, codegen_request
        )
        return codegen_result

    embed_config: EmbedConfig | None = None
    import_map: FrozenDict[str, str] = FrozenDict({})

    if target.has_field(GoPackageSourcesField):
        _maybe_first_party_pkg_analysis, _maybe_first_party_pkg_digest = await MultiGet(
            Get(
                FallibleFirstPartyPkgAnalysis,
                FirstPartyPkgAnalysisRequest(target.address, build_opts=request.build_opts),
            ),
            Get(
                FallibleFirstPartyPkgDigest,
                FirstPartyPkgDigestRequest(target.address, build_opts=request.build_opts),
            ),
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
        pkg_name = _first_party_pkg_analysis.name
        import_path = _first_party_pkg_analysis.import_path
        base_import_path = import_path
        imports = set(_first_party_pkg_analysis.imports)
        if request.for_tests:
            imports.update(_first_party_pkg_analysis.test_imports)
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
        s_files = _first_party_pkg_analysis.s_files
        cgo_files = _first_party_pkg_analysis.cgo_files
        cgo_flags = _first_party_pkg_analysis.cgo_flags
        c_files = _first_party_pkg_analysis.c_files
        h_files = _first_party_pkg_analysis.h_files
        cxx_files = _first_party_pkg_analysis.cxx_files
        objc_files = _first_party_pkg_analysis.m_files
        fortran_files = _first_party_pkg_analysis.f_files
        prebuilt_object_files = _first_party_pkg_analysis.syso_files

        # If the xtest package was requested, then replace analysis with the xtest values.
        if request.for_xtests:
            import_path = f"{import_path}_test"
            pkg_name = f"{pkg_name}_test"
            imports = set(_first_party_pkg_analysis.xtest_imports)
            go_file_names = _first_party_pkg_analysis.xtest_go_files
            s_files = ()
            cgo_files = ()
            cgo_flags = CGoCompilerFlags(
                cflags=(),
                cppflags=(),
                cxxflags=(),
                fflags=(),
                ldflags=(),
                pkg_config=(),
            )
            c_files = ()
            h_files = ()
            cxx_files = ()
            objc_files = ()
            fortran_files = ()
            embed_config = _first_party_pkg_digest.xtest_embed_config

    elif target.has_field(GoThirdPartyPackageDependenciesField):
        import_path = target[GoImportPathField].value
        base_import_path = import_path

        _go_mod_address = target.address.maybe_convert_to_target_generator()
        _go_mod_info = await Get(GoModInfo, GoModInfoRequest(_go_mod_address))
        _third_party_pkg_info = await Get(
            ThirdPartyPkgAnalysis,
            ThirdPartyPkgAnalysisRequest(
                import_path,
                _go_mod_address,
                _go_mod_info.digest,
                _go_mod_info.mod_path,
                build_opts=request.build_opts,
            ),
        )

        # We error if trying to _build_ a package with issues (vs. only generating the target and
        # using in project introspection).
        if _third_party_pkg_info.error:
            raise _third_party_pkg_info.error

        imports = set(_third_party_pkg_info.imports)
        dir_path = _third_party_pkg_info.dir_path
        pkg_name = _third_party_pkg_info.name
        digest = EMPTY_DIGEST
        minimum_go_version = _third_party_pkg_info.minimum_go_version
        go_file_names = _third_party_pkg_info.go_files
        s_files = _third_party_pkg_info.s_files
        embed_config = _third_party_pkg_info.embed_config
        cgo_files = _third_party_pkg_info.cgo_files
        cgo_flags = _third_party_pkg_info.cgo_flags
        c_files = _third_party_pkg_info.c_files
        h_files = _third_party_pkg_info.h_files
        cxx_files = _third_party_pkg_info.cxx_files
        objc_files = _third_party_pkg_info.m_files
        fortran_files = _third_party_pkg_info.f_files
        prebuilt_object_files = _third_party_pkg_info.syso_files

    else:
        raise AssertionError(
            f"Unknown how to build `{target.alias}` target at address {request.address} with Go. "
            "Please open a bug at https://github.com/pantsbuild/pants/issues/new/choose with this "
            "message!"
        )

    assert import_path not in (
        "C",
        "builtin",
        "unsafe",
    ), f"Internal error: Attempting to build marker/intrinsic package `{import_path}`."

    pkg_specific_compiler_flags: tuple[str, ...] = ()
    if target.has_field(GoCompilerFlagsField):
        compiler_flags_field = target.get(GoCompilerFlagsField)
        if compiler_flags_field and compiler_flags_field.value:
            pkg_specific_compiler_flags = compiler_flags_field.value

    pkg_specific_assembler_flags: tuple[str, ...] = ()
    if target.has_field(GoAssemblerFlagsField):
        assembler_flags_field = target.get(GoAssemblerFlagsField)
        if assembler_flags_field and assembler_flags_field.value:
            pkg_specific_assembler_flags = assembler_flags_field.value

    # Add implicit dependencies for Cgo generated code.
    # Note: This rule does not apply to standard library so we do not need to be concerned with excluding these
    # dependencies if we were actually building one of these packages. See the counterpart logic below in the
    # other rule.
    extra_stdlib_dependencies = set(request.extra_stdlib_dependencies)
    if cgo_files:
        extra_stdlib_dependencies.update(["runtime/cgo", "syscall"])

    direct_dependencies = await Get(Targets, DependenciesRequest(target[Dependencies]))

    first_party_dep_import_path_targets = []
    third_party_dep_import_path_targets = []
    codegen_dep_import_path_targets = []
    for dep in direct_dependencies:
        if dep.has_field(GoPackageSourcesField):
            first_party_dep_import_path_targets.append(dep)
        elif dep.has_field(GoImportPathField):
            third_party_dep_import_path_targets.append(dep)
        elif bool(maybe_get_codegen_request_type(dep, request.build_opts, union_membership)):
            codegen_dep_import_path_targets.append(dep)

    first_party_dep_import_path_results = await MultiGet(
        Get(FirstPartyPkgImportPath, FirstPartyPkgImportPathRequest(tgt.address))
        for tgt in first_party_dep_import_path_targets
    )
    first_party_dep_import_paths = {
        result.import_path: tgt.address
        for tgt, result in zip(
            first_party_dep_import_path_targets, first_party_dep_import_path_results
        )
    }

    remaining_imports_set = {*imports, *extra_stdlib_dependencies}
    pkg_dependency_addresses_set: set[Address] = set()

    pkg_dependency_addresses_set.update(
        address
        for dep_import_path, address in first_party_dep_import_paths.items()
        if dep_import_path in remaining_imports_set
    )
    remaining_imports_set.difference_update(
        dep_import_path
        for dep_import_path in first_party_dep_import_paths.keys()
        if dep_import_path in remaining_imports_set
    )

    pkg_dependency_addresses_set.update(
        dep_tgt.address
        for dep_tgt in third_party_dep_import_path_targets
        if dep_tgt[GoImportPathField].value in remaining_imports_set
    )
    remaining_imports_set.difference_update(
        dep_tgt[GoImportPathField].value
        for dep_tgt in third_party_dep_import_path_targets
        if dep_tgt[GoImportPathField].value in remaining_imports_set
    )

    if codegen_dep_import_path_targets:
        go_mod_addr = await Get(OwningGoMod, OwningGoModRequest(request.address))
        import_paths_mapping = await Get(
            GoModuleImportPathsMapping, GoImportPathMappingRequest(go_mod_addr.address)
        )
        for dep_tgt in codegen_dep_import_path_targets:
            codegen_dep_import_path = import_paths_mapping.address_to_import_path.get(
                dep_tgt.address
            )
            if codegen_dep_import_path is None:
                # TODO: Emit warning?
                continue
            if codegen_dep_import_path in remaining_imports_set:
                pkg_dependency_addresses_set.add(dep_tgt.address)
                remaining_imports_set.difference_update([codegen_dep_import_path])

    stdlib_packages = await Get(
        GoStdLibPackages,
        GoStdLibPackagesRequest(
            with_race_detector=request.build_opts.with_race_detector,
            cgo_enabled=request.build_opts.cgo_enabled,
        ),
    )
    stdlib_build_request_gets = []
    for remaining_import in remaining_imports_set:
        if remaining_import in {"builtin", "C", "unsafe"}:
            continue

        if remaining_import not in stdlib_packages:
            continue

        stdlib_build_request_gets.append(
            Get(
                FallibleBuildGoPackageRequest,
                BuildGoPackageRequestForStdlibRequest(
                    import_path=remaining_import,
                    build_opts=request.build_opts,
                ),
            )
        )

    pkg_dependency_addresses = sorted(pkg_dependency_addresses_set)
    maybe_pkg_direct_dependencies = await MultiGet(
        Get(
            FallibleBuildGoPackageRequest,
            BuildGoPackageTargetRequest(address, build_opts=request.build_opts),
        )
        for address in pkg_dependency_addresses
    )
    pkg_stdlib_dependencies = await MultiGet(stdlib_build_request_gets)

    pkg_direct_dependencies = []
    for maybe_pkg_dep in maybe_pkg_direct_dependencies:
        if maybe_pkg_dep.request is None:
            return dataclasses.replace(
                maybe_pkg_dep,
                dependency_failed=True,
            )
        pkg_direct_dependencies.append(maybe_pkg_dep.request)

    for maybe_pkg_dep in pkg_stdlib_dependencies:
        assert maybe_pkg_dep.request
        pkg_direct_dependencies.append(maybe_pkg_dep.request)

    # Allow xtest packages to depend on the base package (with tests).
    if request.for_xtests and any(
        dep_import_path == base_import_path for dep_import_path in imports
    ):
        maybe_base_pkg_dep = await Get(
            FallibleBuildGoPackageRequest,
            BuildGoPackageTargetRequest(
                request.address, for_tests=True, build_opts=request.build_opts
            ),
        )
        if maybe_base_pkg_dep.request is None:
            return dataclasses.replace(
                maybe_base_pkg_dep,
                dependency_failed=True,
            )
        pkg_direct_dependencies.append(maybe_base_pkg_dep.request)

    with_coverage = request.with_coverage
    coverage_config = request.build_opts.coverage_config
    if coverage_config:
        for pattern in coverage_config.import_path_include_patterns:
            with_coverage = with_coverage or match_simple_pattern(pattern)(import_path)

    result = BuildGoPackageRequest(
        digest=digest,
        import_path="main" if request.is_main else import_path,
        pkg_name=pkg_name,
        dir_path=dir_path,
        build_opts=request.build_opts,
        go_files=go_file_names,
        s_files=s_files,
        cgo_files=cgo_files,
        cgo_flags=cgo_flags,
        c_files=c_files,
        header_files=h_files,
        cxx_files=cxx_files,
        objc_files=objc_files,
        fortran_files=fortran_files,
        prebuilt_object_files=prebuilt_object_files,
        minimum_go_version=minimum_go_version,
        direct_dependencies=tuple(sorted(pkg_direct_dependencies, key=lambda p: p.import_path)),
        import_map=import_map,
        for_tests=request.for_tests,
        embed_config=embed_config,
        with_coverage=with_coverage,
        pkg_specific_compiler_flags=tuple(pkg_specific_compiler_flags),
        pkg_specific_assembler_flags=tuple(pkg_specific_assembler_flags),
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


# Return True if coverage should be enabled for a standard library package.
# See https://github.com/golang/go/blob/1e9ff255a130200fcc4ec5e911d28181fce947d5/src/cmd/go/internal/test/test.go#L839-L853
# for the exceptions.
def _is_coverage_enabled_for_stdlib_package(import_path: str, build_opts: GoBuildOptions) -> bool:
    coverage_config = build_opts.coverage_config
    if not coverage_config:
        return False

    # Silently ignore attempts to run coverage on sync/atomic when using atomic coverage mode.
    # Atomic coverage mode uses sync/atomic, so we can't also do coverage on it.
    if coverage_config.cover_mode == GoCoverMode.ATOMIC and import_path == "sync/atomic":
        return False

    # If using the race detector, silently ignore attempts to run coverage on the runtime packages.
    # It will cause the race detector to be invoked before it has been initialized.
    if build_opts.with_race_detector and (
        import_path == "runtime" or import_path.startswith("runtime/internal")
    ):
        return False

    for pattern in coverage_config.import_path_include_patterns:
        if match_simple_pattern(pattern)(import_path):
            return True

    return False


@dataclass(frozen=True)
class _ResolveStdlibEmbedConfigRequest:
    package: GoStdLibPackage


@dataclass(frozen=True)
class _ResolveStdlibEmbedConfigResult:
    embed_config: EmbedConfig | None
    stderr: str | None


@rule
async def resolve_go_stdlib_embed_config(
    request: _ResolveStdlibEmbedConfigRequest,
) -> _ResolveStdlibEmbedConfigResult:
    patterns_json = json.dumps(
        {
            "EmbedPatterns": request.package.embed_patterns,
            "TestEmbedPatterns": [],
            "XTestEmbedPatterns": [],
        }
    ).encode("utf-8")

    embedder, patterns_json_digest = await MultiGet(
        Get(LoadedGoBinary, LoadedGoBinaryRequest("embedcfg", ("main.go",), "./embedder")),
        Get(Digest, CreateDigest([FileContent("patterns.json", patterns_json)])),
    )
    input_digest = await Get(
        Digest,
        MergeDigests((patterns_json_digest, embedder.digest)),
    )
    embed_result = await Get(
        FallibleProcessResult,
        Process(
            ("./embedder", "patterns.json", request.package.pkg_source_path),
            input_digest=input_digest,
            description=f"Create embed mapping for {request.package.import_path}",
            level=LogLevel.DEBUG,
        ),
    )
    if embed_result.exit_code != 0:
        return _ResolveStdlibEmbedConfigResult(
            embed_config=None,
            stderr=embed_result.stderr.decode(),
        )
    metadata = json.loads(embed_result.stdout)
    embed_config = EmbedConfig.from_json_dict(metadata.get("EmbedConfig", {}))
    return _ResolveStdlibEmbedConfigResult(
        embed_config=embed_config,
        stderr=None,
    )


@rule
async def setup_build_go_package_target_request_for_stdlib(
    request: BuildGoPackageRequestForStdlibRequest,
    goroot: GoRoot,
) -> FallibleBuildGoPackageRequest:
    stdlib_packages = await Get(
        GoStdLibPackages,
        GoStdLibPackagesRequest(
            with_race_detector=request.build_opts.with_race_detector,
            cgo_enabled=request.build_opts.cgo_enabled,
        ),
    )

    pkg_info = stdlib_packages[request.import_path]

    direct_dependency_import_pats = set(pkg_info.imports)
    if pkg_info.cgo_files:
        if request.import_path != "runtime/cgo":
            direct_dependency_import_pats.add("runtime/cgo")
        if pkg_info.import_path not in (
            "runtime/cgo",
            "runtime/race",
            "runtime/msan",
            "runtime/asan",
        ):
            direct_dependency_import_pats.add("syscall")

    direct_dependencies_wrapped = await MultiGet(
        Get(
            FallibleBuildGoPackageRequest,
            BuildGoPackageRequestForStdlibRequest(
                import_path=dep_import_path,
                build_opts=request.build_opts,
            ),
        )
        for dep_import_path in sorted(direct_dependency_import_pats)
        if dep_import_path not in {"builtin", "C", "unsafe"}
    )

    direct_dependencies: list[BuildGoPackageRequest] = []
    for dep in direct_dependencies_wrapped:
        assert dep.request is not None
        direct_dependencies.append(dep.request)
    direct_dependencies.sort(key=lambda p: p.import_path)

    with_coverage = _is_coverage_enabled_for_stdlib_package(request.import_path, request.build_opts)

    embed_config: EmbedConfig | None = None
    if pkg_info.embed_patterns and pkg_info.embed_files:
        embed_config_result = await Get(
            _ResolveStdlibEmbedConfigResult, _ResolveStdlibEmbedConfigRequest(pkg_info)
        )
        if not embed_config_result.embed_config:
            assert embed_config_result.stderr is not None
            return FallibleBuildGoPackageRequest(
                request=None,
                import_path=request.import_path,
                exit_code=1,
                stderr=embed_config_result.stderr,
            )
        embed_config = embed_config_result.embed_config

    return FallibleBuildGoPackageRequest(
        request=BuildGoPackageRequest(
            import_path=pkg_info.import_path,
            pkg_name=pkg_info.name,
            digest=EMPTY_DIGEST,
            dir_path=pkg_info.pkg_source_path,
            build_opts=request.build_opts,
            go_files=pkg_info.go_files,
            s_files=pkg_info.s_files,
            direct_dependencies=tuple(direct_dependencies),
            import_map=pkg_info.import_map,
            minimum_go_version=goroot.version,
            cgo_files=pkg_info.cgo_files,
            c_files=pkg_info.c_files,
            header_files=pkg_info.h_files,
            cxx_files=pkg_info.cxx_files,
            objc_files=pkg_info.m_files,
            fortran_files=pkg_info.f_files,
            prebuilt_object_files=pkg_info.syso_files,
            cgo_flags=pkg_info.cgo_flags,
            with_coverage=with_coverage,
            is_stdlib=True,
            embed_config=embed_config,
        ),
        import_path=request.import_path,
    )


def rules():
    return (
        *collect_rules(),
        *build_opts.rules(),
    )
