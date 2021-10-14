# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os

from pants.backend.go.target_types import GoFirstPartyPackageSourcesField, GoImportPathField
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    BuildGoPackageTargetRequest,
    BuiltGoPackage,
)
from pants.backend.go.util_rules.first_party_pkg import FirstPartyPkgInfo, FirstPartyPkgInfoRequest
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.backend.go.util_rules.tests_analysis import GeneratedTestMain, GenerateTestMainRequest
from pants.build_graph.address import Address
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestResult, TestSubsystem
from pants.engine.fs import EMPTY_FILE_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.engine.unions import UnionRule
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


class GoTestFieldSet(TestFieldSet):
    required_fields = (GoFirstPartyPackageSourcesField,)

    sources: GoFirstPartyPackageSourcesField


@rule
async def run_go_tests(field_set: GoTestFieldSet, test_subsystem: TestSubsystem) -> TestResult:
    pkg_info, wrapped_target = await MultiGet(
        Get(FirstPartyPkgInfo, FirstPartyPkgInfoRequest(field_set.address)),
        Get(WrappedTarget, Address, field_set.address),
    )

    target = wrapped_target.target
    import_path = target[GoImportPathField].value

    testmain = await Get(
        GeneratedTestMain,
        GenerateTestMainRequest(
            pkg_info.digest,
            FrozenOrderedSet(
                os.path.join(".", pkg_info.subpath, name) for name in pkg_info.test_files
            ),
            FrozenOrderedSet(
                os.path.join(".", pkg_info.subpath, name) for name in pkg_info.xtest_files
            ),
            import_path=import_path,
        ),
    )

    if not testmain.has_tests and not testmain.has_xtests:
        # Nothing to do so return an empty result.
        # TODO: There should really be a "skipped entirely" mechanism for `TestResult`.
        return TestResult(
            exit_code=0,
            stdout="",
            stdout_digest=EMPTY_FILE_DIGEST,
            stderr="",
            stderr_digest=EMPTY_FILE_DIGEST,
            address=field_set.address,
            output_setting=test_subsystem.output,
        )

    # Construct the build request for the package under test.
    test_pkg_build_request = await Get(
        BuildGoPackageRequest, BuildGoPackageTargetRequest(field_set.address, for_tests=True)
    )
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
            subpath=pkg_info.subpath,
            go_file_names=pkg_info.xtest_files,
            s_file_names=(),  # TODO: Are there .s files for xtest?
            direct_dependencies=tuple(direct_dependencies),
        )
        main_direct_deps.append(xtest_pkg_build_request)

    # Generate the synthetic main package which imports the test and/or xtest packages.
    built_main_pkg = await Get(
        BuiltGoPackage,
        BuildGoPackageRequest(
            import_path="main",
            digest=testmain.digest,
            subpath="",
            go_file_names=(GeneratedTestMain.TEST_MAIN_FILE,),
            s_file_names=(),
            direct_dependencies=tuple(main_direct_deps),
        ),
    )

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
            ["./test_runner"],
            input_digest=binary.digest,
            description=f"Run Go tests: {field_set.address}",
            cache_scope=cache_scope,
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
