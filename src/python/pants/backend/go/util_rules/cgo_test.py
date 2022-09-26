# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals import package_binary
from pants.backend.go.goals.package_binary import GoBinaryFieldSet
from pants.backend.go.goals.test import rules as _test_rules
from pants.backend.go.target_types import GoBinaryTarget, GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    cgo,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.backend.go.util_rules.cgo import CGoCompileRequest, CGoCompileResult
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgAnalysis,
    FallibleFirstPartyPkgDigest,
    FirstPartyPkgAnalysisRequest,
    FirstPartyPkgDigestRequest,
)
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import ResourceTarget
from pants.core.util_rules import source_files
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.process import Process, ProcessResult
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *_test_rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *cgo.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *link.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *tests_analysis.rules(),
            *third_party_pkg.rules(),
            *source_files.rules(),
            *package_binary.rules(),
            QueryRule(BuiltPackage, [GoBinaryFieldSet]),
            QueryRule(FallibleFirstPartyPkgAnalysis, [FirstPartyPkgAnalysisRequest]),
            QueryRule(FallibleFirstPartyPkgDigest, [FirstPartyPkgDigestRequest]),
            QueryRule(CGoCompileResult, [CGoCompileRequest]),
            QueryRule(ProcessResult, (Process,)),
        ],
        target_types=[GoModTarget, GoPackageTarget, GoBinaryTarget, ResourceTarget],
    )
    rule_runner.set_options(
        [
            "--golang-cgo-enabled",
            "--golang-minimum-expected-version=1.16",
            "--go-test-args=-v -bench=.",
        ],
        env_inherit={"PATH"},
    )
    return rule_runner


def test_cgo_compile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
            go_mod(name="mod")
            go_package(name="pkg", dependencies=["foo:foo"])
            go_binary(name="bin")
            """
            ),
            "go.mod": "module example.pantsbuild.org/cgotest\n",
            "foo/BUILD": "resource(source='constants.h')\n",
            "foo/constants.h": "#define NUMBER 2\n",
            "printer.go": dedent(
                """\
            package main

            // /* Define this constant to test passing CFLAGS through to compiler. */
            // #cgo CFLAGS: -DDEFINE_DO_PRINT -I ${SRCDIR}/foo
            //
            // #include <stdio.h>
            // #include <stdlib.h>
            //
            // #include "constants.h"
            //
            // #ifdef DEFINE_DO_PRINT
            // #ifdef NUMBER
            // void do_print(char * str) {
            //   fputs(str, stdout);
            //   fflush(stdout);
            // }
            // #endif
            // #endif
            import "C"
            import "unsafe"

            func Print(s string) {
                cs := C.CString(s)
                C.do_print(cs)
                C.free(unsafe.Pointer(cs))
            }
            """
            ),
            "grok.go": dedent(
                """\
                package main

                func main() {
                    Print("Hello World!\\n")
                }
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    maybe_analysis = rule_runner.request(
        FallibleFirstPartyPkgAnalysis, [FirstPartyPkgAnalysisRequest(tgt.address)]
    )
    assert maybe_analysis.analysis is not None
    analysis = maybe_analysis.analysis
    assert analysis.cgo_files == ("printer.go",)

    maybe_digest = rule_runner.request(
        FallibleFirstPartyPkgDigest, [FirstPartyPkgDigestRequest(tgt.address)]
    )
    assert maybe_digest.pkg_digest is not None
    pkg_digest = maybe_digest.pkg_digest

    cgo_request = CGoCompileRequest(
        import_path=analysis.import_path,
        pkg_name=analysis.name,
        digest=pkg_digest.digest,
        dir_path=analysis.dir_path,
        cgo_files=analysis.cgo_files,
        cgo_flags=analysis.cgo_flags,
    )
    cgo_compile_result = rule_runner.request(CGoCompileResult, [cgo_request])
    assert cgo_compile_result.digest != EMPTY_DIGEST

    tgt = rule_runner.get_target(Address("", target_name="bin"))
    pkg = rule_runner.request(BuiltPackage, [GoBinaryFieldSet.create(tgt)])
    result = rule_runner.request(
        ProcessResult,
        [
            Process(
                argv=["./bin"],
                input_digest=pkg.digest,
                description="Run cgo binary",
            )
        ],
    )
    assert result.stdout.decode() == "Hello World!\n"
