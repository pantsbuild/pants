# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os
from typing import cast

import pystache

from pants.backend.go.target_types import GoFirstPartyPackageSourcesField, GoImportPathField
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    BuildGoPackageTargetRequest,
    BuiltGoPackage,
)
from pants.backend.go.util_rules.first_party_pkg import FirstPartyPkgInfo, FirstPartyPkgInfoRequest
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.backend.go.util_rules.tests_analysis import (
    AnalyzedTestSources,
    AnalyzeTestSourcesRequest,
)
from pants.build_graph.address import Address
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestResult, TestSubsystem
from pants.engine.fs import EMPTY_FILE_DIGEST, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.engine.unions import UnionRule
from pants.util.ordered_set import FrozenOrderedSet

MAIN_TEMPLATE = pystache.parse(
    """\
// Code generated by Pants for test binary. DO NOT EDIT.
package main
import (
    "os"
{{#test_main}}
    "reflect"
{{/test_main}}
    "testing"
    "testing/internal/testdeps"
{{#import_test_pkg}}
    {{#needs_test_pkg}}_test{{/needs_test_pkg}}{{^needs_test_pkg}}_{{/needs_test_pkg}} "{{test_pkg_import_path}}"
{{/import_test_pkg}}
{{#import_xtest_pkg}}
    {{#needs_xtest_pkg}}_test{{/needs_xtest_pkg}}{{^needs_xtest_pkg}}_{{/needs_xtest_pkg}} "{{xtest_pkg_import_path}}"
{{/import_xtest_pkg}}
)
var tests = []testing.InternalTest{
{{#tests}}
    {"{{name}}", {{package}}.{{name}}},
{{/tests}}
}
var benchmarks = []testing.InternalBenchmark{
{{#benchmarks}}
    {"{{name}}", {{package}}.{{name}}},
{{/benchmarks}}
}
var examples = []testing.InternalExample{
{{#examples}}
    {"{{name}}", {{package}}.{{name}}, {{output}}, {{unordered}}},
{{/examples}}
}

func init() {
    testdeps.ImportPath = "{{import_path}}"
}

func main() {
    m := testing.MainStart(testdeps.TestDeps{}, tests, benchmarks, examples)
{{#test_main}}
    {{package}}.{{name}}(m)
    os.Exit(int(reflect.ValueOf(m).Elem().FieldByName("exitCode").Int()))
{{/test_main}}
{{^test_main}}
    os.Exit(m.Run())
{{/test_main}}
}
"""
)


def generate_main(
    analyzed_sources: AnalyzedTestSources,
    import_path: str,
    has_test_files: bool,
    has_xtest_files: bool,
) -> str:
    context = {
        "import_path": import_path,
        "import_test_pkg": has_test_files,
        "import_xtest_pkg": has_xtest_files,
        "needs_test_pkg": analyzed_sources.has_at_least_one_test(),
        "needs_xtest_pkg": analyzed_sources.has_at_least_one_xtest(),
        "test_pkg_import_path": import_path,
        "xtest_pkg_import_path": f"{import_path}_test",
        "tests": [{"package": test.package, "name": test.name} for test in analyzed_sources.tests],
        "benchmarks": [
            {
                "package": benchmark.package,
                "name": benchmark.name,
            }
            for benchmark in analyzed_sources.benchmarks
        ],
        "examples": [
            {
                "package": example.package,
                "name": example.name,
                # TODO: Does JSON string quoting handle all escaping in Go-compatible way?
                "output": json.dumps(example.output),
                "unordered": "true" if example.unordered else "false",
            }
            for example in analyzed_sources.examples
        ],
    }

    if analyzed_sources.test_main:
        context["test_main"] = {
            "package": analyzed_sources.test_main.package,
            "name": analyzed_sources.test_main.name,
        }

    renderer = pystache.Renderer(escape=lambda u: u)
    return cast(str, renderer.render(MAIN_TEMPLATE, context))


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

    analyzed_sources = await Get(
        AnalyzedTestSources,
        AnalyzeTestSourcesRequest(
            pkg_info.digest,
            FrozenOrderedSet(
                os.path.join(".", pkg_info.subpath, name) for name in pkg_info.test_files
            ),
            FrozenOrderedSet(
                os.path.join(".", pkg_info.subpath, name) for name in pkg_info.xtest_files
            ),
        ),
    )

    if (
        not analyzed_sources.has_at_least_one_test()
        and not analyzed_sources.has_at_least_one_xtest()
    ):
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

    # TODO: Generate a synthetic package for any xtest files.
    if analyzed_sources.has_at_least_one_xtest():
        raise NotImplementedError(
            'The Go plugin does not currently support external tests ("xtest"\'s).'
        )

    # Generate the synthetic main package which imports the test and/or xtest packages.
    main_content = FileContent(
        path="_testmain.go",
        content=generate_main(
            analyzed_sources, import_path, bool(pkg_info.test_files), bool(pkg_info.xtest_files)
        ).encode("utf-8"),
    )
    main_sources_digest = await Get(Digest, CreateDigest([main_content]))
    main_import_path = "main"

    built_main_pkg = await Get(
        BuiltGoPackage,
        BuildGoPackageRequest(
            import_path=main_import_path,
            digest=main_sources_digest,
            subpath="",
            go_file_names=(main_content.path,),
            s_file_names=(),
            direct_dependencies=tuple(main_direct_deps),
        ),
    )

    main_pkg_a_file_path = built_main_pkg.import_paths_to_pkg_a_files[main_import_path]
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
