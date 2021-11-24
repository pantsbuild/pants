# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Sequence

from pants.backend.go.subsystems.gotest import GoTestSubsystem
from pants.backend.go.target_types import GoPackageSourcesField, SkipGoTestsField
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    FallibleBuildGoPackageRequest,
    FallibleBuiltGoPackage,
)
from pants.backend.go.util_rules.build_pkg_target import BuildGoPackageTargetRequest
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgInfo,
    FirstPartyPkgInfoRequest,
)
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.backend.go.util_rules.tests_analysis import GeneratedTestMain, GenerateTestMainRequest
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestResult, TestSubsystem
from pants.engine.fs import EMPTY_FILE_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

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
    "timeout": True,
    "trace": True,
    "v": False,
}


class GoTestFieldSet(TestFieldSet):
    required_fields = (GoPackageSourcesField,)

    sources: GoPackageSourcesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGoTestsField).value


def transform_test_args(args: Sequence[str]) -> tuple[str, ...]:
    result = []

    i = 0
    next_arg_is_option_value = False
    while i < len(args):
        arg = args[i]
        i += 1

        # If this argument is an option value, then append it to the result and continue to next argument.
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
            rewritten_arg = f"{arg[0:start_index]}test.{arg_name}{option_value}"
            result.append(rewritten_arg)
            if TEST_FLAGS[arg_name] and option_value == "":
                next_arg_is_option_value = True
        else:
            result.append(arg)

    result.extend(args[i:])
    return tuple(result)


@rule(desc="Test with Go", level=LogLevel.DEBUG)
async def run_go_tests(
    field_set: GoTestFieldSet, test_subsystem: TestSubsystem, go_test_subsystem: GoTestSubsystem
) -> TestResult:
    maybe_pkg_info = await Get(
        FallibleFirstPartyPkgInfo, FirstPartyPkgInfoRequest(field_set.address)
    )

    def compilation_failure(exit_code: int, stderr: str) -> TestResult:
        return TestResult(
            exit_code=exit_code,
            stdout="",
            stderr=stderr,
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr_digest=EMPTY_FILE_DIGEST,
            address=field_set.address,
            output_setting=test_subsystem.output,
        )

    if maybe_pkg_info.info is None:
        assert maybe_pkg_info.stderr is not None
        return compilation_failure(maybe_pkg_info.exit_code, maybe_pkg_info.stderr)

    pkg_info = maybe_pkg_info.info
    import_path = pkg_info.import_path

    testmain = await Get(
        GeneratedTestMain,
        GenerateTestMainRequest(
            pkg_info.digest,
            FrozenOrderedSet(
                os.path.join(".", pkg_info.dir_path, name) for name in pkg_info.test_files
            ),
            FrozenOrderedSet(
                os.path.join(".", pkg_info.dir_path, name) for name in pkg_info.xtest_files
            ),
            import_path,
            field_set.address,
        ),
    )

    if testmain.failed_exit_code_and_stderr is not None:
        return compilation_failure(*testmain.failed_exit_code_and_stderr)

    if not testmain.has_tests and not testmain.has_xtests:
        return TestResult.skip(field_set.address, output_setting=test_subsystem.output)

    # Construct the build request for the package under test.
    maybe_test_pkg_build_request = await Get(
        FallibleBuildGoPackageRequest,
        BuildGoPackageTargetRequest(field_set.address, for_tests=True),
    )
    if maybe_test_pkg_build_request.request is None:
        assert maybe_test_pkg_build_request.stderr is not None
        return compilation_failure(
            maybe_test_pkg_build_request.exit_code, maybe_test_pkg_build_request.stderr
        )
    test_pkg_build_request = maybe_test_pkg_build_request.request

    main_direct_deps = [test_pkg_build_request]

    if testmain.has_xtests:
        # Build a synthetic package for xtests where the import path is the same as the package under test
        # but with "_test" appended.
        #
        # Subset the direct dependencies to only the dependencies used by the xtest code. (Dependency
        # inference will have included all of the regular, test, and xtest dependencies of the package in
        # the build graph.) Moreover, ensure that any import of the package under test is on the _test_
        # version of the package that was just built.
        dep_by_import_path = {
            dep.import_path: dep for dep in test_pkg_build_request.direct_dependencies
        }
        direct_dependencies: OrderedSet[BuildGoPackageRequest] = OrderedSet()
        for xtest_import in pkg_info.xtest_imports:
            if xtest_import == pkg_info.import_path:
                direct_dependencies.add(test_pkg_build_request)
            elif xtest_import in dep_by_import_path:
                direct_dependencies.add(dep_by_import_path[xtest_import])

        xtest_pkg_build_request = BuildGoPackageRequest(
            import_path=f"{import_path}_test",
            digest=pkg_info.digest,
            dir_path=pkg_info.dir_path,
            go_file_names=pkg_info.xtest_files,
            s_file_names=(),  # TODO: Are there .s files for xtest?
            direct_dependencies=tuple(direct_dependencies),
            minimum_go_version=pkg_info.minimum_go_version,
        )
        main_direct_deps.append(xtest_pkg_build_request)

    # Generate the synthetic main package which imports the test and/or xtest packages.
    maybe_built_main_pkg = await Get(
        FallibleBuiltGoPackage,
        BuildGoPackageRequest(
            import_path="main",
            digest=testmain.digest,
            dir_path="",
            go_file_names=(GeneratedTestMain.TEST_MAIN_FILE,),
            s_file_names=(),
            direct_dependencies=tuple(main_direct_deps),
            minimum_go_version=pkg_info.minimum_go_version,
        ),
    )
    if maybe_built_main_pkg.output is None:
        assert maybe_built_main_pkg.stderr is not None
        compilation_failure(maybe_built_main_pkg.exit_code, maybe_built_main_pkg.stderr)
    built_main_pkg = maybe_built_main_pkg.output

    main_pkg_a_file_path = built_main_pkg.import_paths_to_pkg_a_files["main"]
    import_config = await Get(
        ImportConfig, ImportConfigRequest(built_main_pkg.import_paths_to_pkg_a_files)
    )
    input_digest = await Get(Digest, MergeDigests([built_main_pkg.digest, import_config.digest]))

    binary = await Get(
        LinkedGoBinary,
        LinkGoBinaryRequest(
            input_digest=input_digest,
            archives=(main_pkg_a_file_path,),
            import_config_path=import_config.CONFIG_PATH,
            output_filename="./test_runner",  # TODO: Name test binary the way that `go` does?
            description=f"Link Go test binary for {field_set.address}",
        ),
    )

    cache_scope = (
        ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
    )

    result = await Get(
        FallibleProcessResult,
        Process(
            ["./test_runner", *transform_test_args(go_test_subsystem.args)],
            input_digest=binary.digest,
            description=f"Run Go tests: {field_set.address}",
            cache_scope=cache_scope,
            level=LogLevel.DEBUG,
        ),
    )
    return TestResult.from_fallible_process_result(result, field_set.address, test_subsystem.output)


@rule
async def generate_go_tests_debug_request(field_set: GoTestFieldSet) -> TestDebugRequest:
    raise NotImplementedError("This is a stub.")


def rules():
    return [
        *collect_rules(),
        UnionRule(TestFieldSet, GoTestFieldSet),
    ]
