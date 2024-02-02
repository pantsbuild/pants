# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import json
import logging
import os
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from pants.backend.go.dependency_inference import GoModuleImportPathsMapping
from pants.backend.go.subsystems.gotest import GoTestSubsystem
from pants.backend.go.target_type_rules import GoImportPathMappingRequest
from pants.backend.go.target_types import (
    GoPackageSourcesField,
    GoTestExtraEnvVarsField,
    GoTestTimeoutField,
    SkipGoTestsField,
)
from pants.backend.go.util_rules.build_opts import GoBuildOptions, GoBuildOptionsFromTargetRequest
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    BuiltGoPackage,
    FallibleBuildGoPackageRequest,
    FallibleBuiltGoPackage,
)
from pants.backend.go.util_rules.build_pkg_target import (
    BuildGoPackageRequestForStdlibRequest,
    BuildGoPackageTargetRequest,
)
from pants.backend.go.util_rules.coverage import (
    GenerateCoverageSetupCodeRequest,
    GenerateCoverageSetupCodeResult,
    GoCoverageConfig,
    GoCoverageData,
    GoCoverMode,
)
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FallibleFirstPartyPkgDigest,
    FirstPartyPkgAnalysis,
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgDigest,
    FirstPartyPkgDigestRequest,
)
from pants.backend.go.util_rules.go_mod import OwningGoMod, OwningGoModRequest
from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.import_analysis import GoStdLibPackages, GoStdLibPackagesRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.backend.go.util_rules.pkg_analyzer import PackageAnalyzerSetup
from pants.backend.go.util_rules.tests_analysis import GeneratedTestMain, GenerateTestMainRequest
from pants.build_graph.address import Address
from pants.core.goals.test import TestExtraEnv, TestFieldSet, TestRequest, TestResult, TestSubsystem
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import EMPTY_FILE_DIGEST, AddPrefix, Digest, MergeDigests
from pants.engine.internals.native_engine import EMPTY_DIGEST, Snapshot
from pants.engine.process import (
    Process,
    ProcessCacheScope,
    ProcessResult,
    ProcessResultWithRetries,
    ProcessWithRetries,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, SourcesField, Target, Targets
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)

# Known options to Go test binaries. Only these options will be transformed by `transform_test_args`.
# The bool value represents whether the option is expected to take a value or not.
# To regenerate this list, run `go run ./gentestflags.go` and copy the output below.
TEST_FLAGS = {
    "bench": True,
    "benchmem": False,
    "benchtime": True,
    "blockprofile": True,
    "blockprofilerate": True,
    "count": True,
    "coverprofile": True,
    "cpu": True,
    "cpuprofile": True,
    "failfast": False,
    "fuzz": True,
    "fuzzminimizetime": True,
    "fuzztime": True,
    "list": True,
    "memprofile": True,
    "memprofilerate": True,
    "mutexprofile": True,
    "mutexprofilefraction": True,
    "outputdir": True,
    "parallel": True,
    "run": True,
    "short": False,
    "shuffle": True,
    "skip": True,
    "timeout": True,
    "trace": True,
    "v": False,
}


@dataclass(frozen=True)
class GoTestFieldSet(TestFieldSet):
    required_fields = (GoPackageSourcesField,)

    sources: GoPackageSourcesField
    dependencies: Dependencies
    timeout: GoTestTimeoutField
    extra_env_vars: GoTestExtraEnvVarsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGoTestsField).value


class GoTestRequest(TestRequest):
    tool_subsystem = GoTestSubsystem
    field_set_type = GoTestFieldSet


@dataclass(frozen=True)
class PrepareGoTestBinaryCoverageConfig:
    coverage_mode: GoCoverMode
    coverage_packages: tuple[str, ...]


@dataclass(frozen=True)
class PrepareGoTestBinaryRequest:
    field_set: GoTestFieldSet
    coverage: PrepareGoTestBinaryCoverageConfig | None


@dataclass(frozen=True)
class PrepareGoTestBinaryResult:
    test_binary_digest: Digest
    test_binary_path: str
    import_path: str
    pkg_digest: FirstPartyPkgDigest
    pkg_analysis: FirstPartyPkgAnalysis


@dataclass(frozen=True)
class FalliblePrepareGoTestBinaryResult:
    binary: PrepareGoTestBinaryResult | None
    stdout: str
    stderr: str
    exit_code: int


def transform_test_args(args: Sequence[str], timeout_field_value: int | None) -> tuple[str, ...]:
    result = []
    i = 0
    next_arg_is_option_value = False
    timeout_is_set = False
    while i < len(args):
        arg = args[i]
        i += 1

        # If this argument is an option value, then append it to the result and continue to next
        # argument.
        if next_arg_is_option_value:
            result.append(arg)
            next_arg_is_option_value = False
            continue

        # Non-arguments stop option processing.
        if arg[0] != "-":
            result.append(arg)
            break

        # Stop processing since "-" is a non-argument and "--" is terminator.
        if arg == "-" or arg == "--":
            result.append(arg)
            break

        start_index = 2 if arg[1] == "-" else 1
        equals_index = arg.find("=", start_index)
        if equals_index != -1:
            arg_name = arg[start_index:equals_index]
            option_value = arg[equals_index:]
        else:
            arg_name = arg[start_index:]
            option_value = ""

        if arg_name in TEST_FLAGS:
            if arg_name == "timeout":
                timeout_is_set = True

            rewritten_arg = f"{arg[0:start_index]}test.{arg_name}{option_value}"
            result.append(rewritten_arg)

            no_opt_provided = TEST_FLAGS[arg_name] and option_value == ""
            if no_opt_provided:
                next_arg_is_option_value = True
        else:
            result.append(arg)

    if not timeout_is_set and timeout_field_value is not None:
        result.append(f"-test.timeout={timeout_field_value}s")

    result.extend(args[i:])
    return tuple(result)


def _lift_build_requests_with_coverage(
    roots: Iterable[BuildGoPackageRequest],
) -> list[BuildGoPackageRequest]:
    result: list[BuildGoPackageRequest] = []

    queue: deque[BuildGoPackageRequest] = deque()
    seen: set[BuildGoPackageRequest] = set()
    queue.extend(roots)
    seen.update(roots)

    while queue:
        build_request = queue.popleft()
        if build_request.with_coverage:
            result.append(build_request)
        unseen = [dd for dd in build_request.direct_dependencies if dd not in seen]
        queue.extend(unseen)
        seen.update(unseen)

    return result


@rule(desc="Prepare Go test binary", level=LogLevel.DEBUG)
async def prepare_go_test_binary(
    request: PrepareGoTestBinaryRequest,
    analyzer: PackageAnalyzerSetup,
) -> FalliblePrepareGoTestBinaryResult:
    go_mod_addr = await Get(OwningGoMod, OwningGoModRequest(request.field_set.address))
    package_mapping, build_opts = await MultiGet(
        Get(GoModuleImportPathsMapping, GoImportPathMappingRequest(go_mod_addr.address)),
        Get(GoBuildOptions, GoBuildOptionsFromTargetRequest(request.field_set.address)),
    )

    maybe_pkg_analysis, maybe_pkg_digest, dependencies = await MultiGet(
        Get(
            FallibleFirstPartyPkgAnalysis,
            FirstPartyPkgAnalysisRequest(request.field_set.address, build_opts=build_opts),
        ),
        Get(
            FallibleFirstPartyPkgDigest,
            FirstPartyPkgDigestRequest(request.field_set.address, build_opts=build_opts),
        ),
        Get(Targets, DependenciesRequest(request.field_set.dependencies)),
    )

    def compilation_failure(
        exit_code: int, stdout: str | None, stderr: str | None
    ) -> FalliblePrepareGoTestBinaryResult:
        return FalliblePrepareGoTestBinaryResult(
            binary=None,
            stdout=stdout or "",
            stderr=stderr or "",
            exit_code=exit_code,
        )

    if maybe_pkg_analysis.analysis is None:
        assert maybe_pkg_analysis.stderr is not None
        return compilation_failure(maybe_pkg_analysis.exit_code, None, maybe_pkg_analysis.stderr)
    if maybe_pkg_digest.pkg_digest is None:
        assert maybe_pkg_digest.stderr is not None
        return compilation_failure(maybe_pkg_digest.exit_code, None, maybe_pkg_digest.stderr)

    pkg_analysis = maybe_pkg_analysis.analysis
    pkg_digest = maybe_pkg_digest.pkg_digest
    import_path = pkg_analysis.import_path

    with_coverage = False
    if request.coverage is not None:
        with_coverage = True
        build_opts = dataclasses.replace(
            build_opts,
            coverage_config=GoCoverageConfig(
                cover_mode=request.coverage.coverage_mode,
                import_path_include_patterns=request.coverage.coverage_packages,
            ),
        )

    testmain = await Get(
        GeneratedTestMain,
        GenerateTestMainRequest(
            digest=pkg_digest.digest,
            test_paths=FrozenOrderedSet(
                os.path.join(pkg_analysis.dir_path, name) for name in pkg_analysis.test_go_files
            ),
            xtest_paths=FrozenOrderedSet(
                os.path.join(pkg_analysis.dir_path, name) for name in pkg_analysis.xtest_go_files
            ),
            import_path=import_path,
            register_cover=with_coverage,
            address=request.field_set.address,
        ),
    )

    if testmain.failed_exit_code_and_stderr is not None:
        _exit_code, _stderr = testmain.failed_exit_code_and_stderr
        return compilation_failure(_exit_code, None, _stderr)

    if not testmain.has_tests and not testmain.has_xtests:
        return FalliblePrepareGoTestBinaryResult(
            binary=None,
            stdout="",
            stderr="",
            exit_code=0,
        )

    testmain_analysis_input_digest = await Get(
        Digest, MergeDigests([testmain.digest, analyzer.digest])
    )
    testmain_analysis = await Get(
        ProcessResult,
        Process(
            (analyzer.path, "."),
            input_digest=testmain_analysis_input_digest,
            description=f"Determine metadata for testmain for {request.field_set.address}",
            level=LogLevel.DEBUG,
            env={
                "CGO_ENABLED": "1" if build_opts.cgo_enabled else "0",
            },
        ),
    )
    testmain_analysis_json = json.loads(testmain_analysis.stdout.decode())

    stdlib_packages = await Get(
        GoStdLibPackages,
        GoStdLibPackagesRequest(
            with_race_detector=build_opts.with_race_detector,
            cgo_enabled=build_opts.cgo_enabled,
        ),
    )

    inferred_dependencies: set[Address] = set()
    stdlib_build_request_gets = []
    for dep_import_path in testmain_analysis_json.get("Imports", []):
        if dep_import_path == import_path:
            continue  # test pkg dep added manually later

        if dep_import_path in stdlib_packages:
            stdlib_build_request_gets.append(
                Get(
                    FallibleBuildGoPackageRequest,
                    BuildGoPackageRequestForStdlibRequest(
                        import_path=dep_import_path,
                        build_opts=build_opts,
                    ),
                )
            )
            continue

        candidate_packages = package_mapping.mapping.get(dep_import_path)
        if candidate_packages:
            if candidate_packages.infer_all:
                inferred_dependencies.update(candidate_packages.addresses)
            else:
                if len(candidate_packages.addresses) > 1:
                    # TODO(#12761): Use ExplicitlyProvidedDependencies for disambiguation.
                    logger.warning(
                        f"Ambiguous mapping for import path {dep_import_path} on packages at addresses: {candidate_packages}"
                    )
                elif len(candidate_packages.addresses) == 1:
                    inferred_dependencies.add(candidate_packages.addresses[0])
                else:
                    logger.debug(
                        f"Unable to infer dependency for import path '{dep_import_path}' "
                        f"in go_package at address '{request.field_set.address}'."
                    )
        else:
            logger.debug(
                f"Unable to infer dependency for import path '{dep_import_path}' "
                f"in go_package at address '{request.field_set.address}'."
            )

    fallible_testmain_import_build_requests = await MultiGet(
        Get(
            FallibleBuildGoPackageRequest,
            BuildGoPackageTargetRequest(
                address=address,
                build_opts=build_opts,
            ),
        )
        for address in sorted(inferred_dependencies)
    )

    testmain_import_build_requests: list[BuildGoPackageRequest] = []
    for build_request in fallible_testmain_import_build_requests:
        if build_request.request is None:
            return compilation_failure(build_request.exit_code, None, build_request.stderr)
        testmain_import_build_requests.append(build_request.request)

    stdlib_build_requests = await MultiGet(stdlib_build_request_gets)
    for build_request in stdlib_build_requests:
        assert build_request.request is not None
        testmain_import_build_requests.append(build_request.request)

    # Construct the build request for the package under test.
    maybe_test_pkg_build_request = await Get(
        FallibleBuildGoPackageRequest,
        BuildGoPackageTargetRequest(
            request.field_set.address,
            for_tests=True,
            with_coverage=with_coverage,
            build_opts=build_opts,
        ),
    )
    if maybe_test_pkg_build_request.request is None:
        assert maybe_test_pkg_build_request.stderr is not None
        return compilation_failure(
            maybe_test_pkg_build_request.exit_code, None, maybe_test_pkg_build_request.stderr
        )
    test_pkg_build_request = maybe_test_pkg_build_request.request

    # Determine the direct dependencies of the generated main package. The test package itself is always a
    # dependency. Add the xtests package as well if any xtests exist.
    main_direct_deps = [test_pkg_build_request, *testmain_import_build_requests]
    if testmain.has_xtests:
        # Build a synthetic package for xtests where the import path is the same as the package under test
        # but with "_test" appended.
        maybe_xtest_pkg_build_request = await Get(
            FallibleBuildGoPackageRequest,
            BuildGoPackageTargetRequest(
                request.field_set.address,
                for_xtests=True,
                with_coverage=with_coverage,
                build_opts=build_opts,
            ),
        )
        if maybe_xtest_pkg_build_request.request is None:
            assert maybe_xtest_pkg_build_request.stderr is not None
            return compilation_failure(
                maybe_xtest_pkg_build_request.exit_code, None, maybe_xtest_pkg_build_request.stderr
            )
        xtest_pkg_build_request = maybe_xtest_pkg_build_request.request
        main_direct_deps.append(xtest_pkg_build_request)

    # Generate coverage setup code for the test main if coverage is enabled.
    #
    # Note: Go coverage analysis is a form of codegen. It rewrites the Go source code at issue to include explicit
    # references to "coverage variables" which contain the statement counts for coverage analysis. The test main
    # generated for a Go test binary has to explicitly reference the coverage variables generated by this codegen and
    # register them with the coverage runtime.
    coverage_setup_digest = EMPTY_DIGEST
    coverage_setup_files = []
    if with_coverage:
        # Scan the tree of BuildGoPackageRequest's and lift any packages with coverage enabled to be direct
        # dependencies of the generated main package. This facilitates registration of the code coverage
        # setup functions.
        coverage_transitive_deps = _lift_build_requests_with_coverage(main_direct_deps)
        coverage_transitive_deps.sort(key=lambda build_req: build_req.import_path)
        main_direct_deps.extend(coverage_transitive_deps)

        # Build the `main_direct_deps` when in coverage mode to obtain the "coverage variables" for those packages.
        built_main_direct_deps = await MultiGet(
            Get(BuiltGoPackage, BuildGoPackageRequest, build_req) for build_req in main_direct_deps
        )
        coverage_metadata = [
            pkg.coverage_metadata for pkg in built_main_direct_deps if pkg.coverage_metadata
        ]
        coverage_setup_result = await Get(
            GenerateCoverageSetupCodeResult,
            GenerateCoverageSetupCodeRequest(
                packages=FrozenOrderedSet(coverage_metadata),
                cover_mode=request.coverage.coverage_mode,  # type: ignore[union-attr] # gated on with_coverage
            ),
        )
        coverage_setup_digest = coverage_setup_result.digest
        coverage_setup_files = [GenerateCoverageSetupCodeResult.PATH]

    testmain_input_digest = await Get(
        Digest, MergeDigests([testmain.digest, coverage_setup_digest])
    )

    # Generate the synthetic main package which imports the test and/or xtest packages.
    maybe_built_main_pkg = await Get(
        FallibleBuiltGoPackage,
        BuildGoPackageRequest(
            import_path="main",
            pkg_name="main",
            digest=testmain_input_digest,
            dir_path="",
            build_opts=build_opts,
            go_files=(GeneratedTestMain.TEST_MAIN_FILE, *coverage_setup_files),
            s_files=(),
            direct_dependencies=tuple(main_direct_deps),
            minimum_go_version=pkg_analysis.minimum_go_version,
        ),
    )
    if maybe_built_main_pkg.output is None:
        assert maybe_built_main_pkg.stderr is not None
        return compilation_failure(
            maybe_built_main_pkg.exit_code, maybe_built_main_pkg.stdout, maybe_built_main_pkg.stderr
        )
    built_main_pkg = maybe_built_main_pkg.output

    main_pkg_a_file_path = built_main_pkg.import_paths_to_pkg_a_files["main"]

    binary = await Get(
        LinkedGoBinary,
        LinkGoBinaryRequest(
            input_digest=built_main_pkg.digest,
            archives=(main_pkg_a_file_path,),
            build_opts=build_opts,
            import_paths_to_pkg_a_files=built_main_pkg.import_paths_to_pkg_a_files,
            output_filename="./test_runner",  # TODO: Name test binary the way that `go` does?
            description=f"Link Go test binary for {request.field_set.address}",
        ),
    )

    return FalliblePrepareGoTestBinaryResult(
        binary=PrepareGoTestBinaryResult(
            test_binary_digest=binary.digest,
            test_binary_path="./test_runner",
            import_path=import_path,
            pkg_digest=pkg_digest,
            pkg_analysis=pkg_analysis,
        ),
        stdout="",
        stderr="",
        exit_code=0,
    )


_PROFILE_OPTIONS: dict[str, str] = {
    "blockprofile": "--go-test-block-profile",
    "coverprofile": "--test-use-coverage",
    "cpuprofie": "--go-test-cpu-profile",
    "memprofile": "--go-test-mem-profile",
    "mutexprofile": "--go-test-mutex-profile",
    "trace": "--go-test-trace",
}


def _ensure_no_profile_options(args: Sequence[str]) -> None:
    for arg in args:
        # Non-arguments stop option processing.
        if arg[0] != "-":
            break

        # Stop processing since "-" is a non-argument and "--" is terminator.
        if arg == "-" or arg == "--":
            break

        for go_name, pants_name in _PROFILE_OPTIONS.items():
            if arg == f"-test.{go_name}" or arg.startswith(f"-test.{go_name}="):
                raise ValueError(
                    f"The `[go-test].args` option contains the Go test option `-{go_name}`. "
                    "This is not supported because Pants needs to manage that option in order to know to "
                    "extract the applicable output file from the execution sandbox. "
                    f"Please use the Pants `{pants_name}` option instead."
                )


@rule(desc="Test with Go", level=LogLevel.DEBUG)
async def run_go_tests(
    batch: GoTestRequest.Batch[GoTestFieldSet, Any],
    test_subsystem: TestSubsystem,
    go_test_subsystem: GoTestSubsystem,
    test_extra_env: TestExtraEnv,
    goroot: GoRoot,
) -> TestResult:
    field_set = batch.single_element

    coverage: PrepareGoTestBinaryCoverageConfig | None = None
    if test_subsystem.use_coverage:
        coverage = PrepareGoTestBinaryCoverageConfig(
            coverage_mode=go_test_subsystem.coverage_mode,
            coverage_packages=go_test_subsystem.coverage_packages,
        )

    fallible_test_binary = await Get(
        FalliblePrepareGoTestBinaryResult,
        PrepareGoTestBinaryRequest(field_set=field_set, coverage=coverage),
    )

    if fallible_test_binary.exit_code != 0:
        return TestResult(
            exit_code=fallible_test_binary.exit_code,
            stdout_bytes=fallible_test_binary.stdout.encode(),
            stderr_bytes=fallible_test_binary.stderr.encode(),
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            addresses=(field_set.address,),
            output_setting=test_subsystem.output,
            result_metadata=None,
        )

    test_binary = fallible_test_binary.binary
    if test_binary is None:
        return TestResult.no_tests_found(field_set.address, output_setting=test_subsystem.output)

    # To emulate Go's test runner, we set the working directory to the path of the `go_package`.
    # This allows tests to open dependencies on `file` targets regardless of where they are
    # located. See https://dave.cheney.net/2016/05/10/test-fixtures-in-go.
    working_dir = field_set.address.spec_path
    field_set_extra_env, dependencies, binary_with_prefix = await MultiGet(
        Get(EnvironmentVars, EnvironmentVarsRequest(field_set.extra_env_vars.value or ())),
        Get(Targets, DependenciesRequest(field_set.dependencies)),
        Get(Digest, AddPrefix(test_binary.test_binary_digest, working_dir)),
    )
    files_sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            (dep.get(SourcesField) for dep in dependencies),
            for_sources_types=(FileSourceField,),
            enable_codegen=True,
        ),
    )
    test_input_digest = await Get(
        Digest, MergeDigests((binary_with_prefix, files_sources.snapshot.digest))
    )

    extra_env = {
        **test_extra_env.env,
        # NOTE: field_set_extra_env intentionally after `test_extra_env` to allow overriding within
        # `go_package`.
        **field_set_extra_env,
    }

    # Add $GOROOT/bin to the PATH just as `go test` does.
    # See https://github.com/golang/go/blob/master/src/cmd/go/internal/test/test.go#L1384
    goroot_bin_path = os.path.join("{CHROOT}", goroot.path, "bin")
    if "PATH" in extra_env:
        extra_env["PATH"] = f"{goroot_bin_path}:{extra_env['PATH']}"
    else:
        extra_env["PATH"] = goroot_bin_path

    cache_scope = (
        ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )

    test_flags = transform_test_args(
        go_test_subsystem.args,
        field_set.timeout.calculate_from_global_options(test_subsystem),
    )

    _ensure_no_profile_options(test_flags)

    output_files = []
    maybe_profile_args = []
    output_test_binary = go_test_subsystem.output_test_binary

    if test_subsystem.use_coverage:
        maybe_profile_args.append("-test.coverprofile=cover.out")
        output_files.append("cover.out")

    if go_test_subsystem.block_profile:
        maybe_profile_args.append("-test.blockprofile=block.out")
        output_files.append("block.out")
        output_test_binary = True

    if go_test_subsystem.cpu_profile:
        maybe_profile_args.append("-test.cpuprofile=cpu.out")
        output_files.append("cpu.out")
        output_test_binary = True

    if go_test_subsystem.mem_profile:
        maybe_profile_args.append("-test.memprofile=mem.out")
        output_files.append("mem.out")
        output_test_binary = True

    if go_test_subsystem.mutex_profile:
        maybe_profile_args.append("-test.mutexprofile=mutex.out")
        output_files.append("mutex.out")
        output_test_binary = True

    if go_test_subsystem.trace:
        maybe_profile_args.append("-test.trace=trace.out")
        output_files.append("trace.out")

    go_test_process = Process(
        argv=(
            test_binary.test_binary_path,
            *test_flags,
            *maybe_profile_args,
        ),
        env=extra_env,
        input_digest=test_input_digest,
        description=f"Run Go tests: {field_set.address}",
        cache_scope=cache_scope,
        working_directory=working_dir,
        output_files=output_files,
        level=LogLevel.DEBUG,
        immutable_input_digests={".goroot": goroot.digest},
    )
    results = await Get(
        ProcessResultWithRetries,
        ProcessWithRetries(go_test_process, test_subsystem.attempts_default),
    )

    coverage_data: GoCoverageData | None = None
    if test_subsystem.use_coverage:
        coverage_data = GoCoverageData(
            coverage_digest=results.last.output_digest,
            import_path=test_binary.import_path,
            sources_digest=test_binary.pkg_digest.digest,
            sources_dir_path=test_binary.pkg_analysis.dir_path,
            pkg_target_address=field_set.address,
        )

    output_files = [x for x in output_files if x != "cover.out"]
    extra_output: Snapshot | None = None
    if output_files or output_test_binary:
        output_digest = results.last.output_digest
        if output_test_binary:
            output_digest = await Get(
                Digest, MergeDigests([output_digest, test_binary.test_binary_digest])
            )
        extra_output = await Get(Snapshot, Digest, output_digest)

    return TestResult.from_fallible_process_result(
        process_results=results.results,
        address=field_set.address,
        output_setting=test_subsystem.output,
        coverage_data=coverage_data,
        extra_output=extra_output,
        log_extra_output=True,
    )


def rules():
    return [
        *collect_rules(),
        *GoTestRequest.rules(),
    ]
