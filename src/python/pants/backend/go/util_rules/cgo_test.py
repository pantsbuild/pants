# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
import pkgutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
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
from pants.backend.go.util_rules.build_opts import GoBuildOptions
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
        target_types=[
            GoModTarget,
            GoPackageTarget,
            GoBinaryTarget,
            ResourceTarget,
        ],
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
        FallibleFirstPartyPkgAnalysis,
        [FirstPartyPkgAnalysisRequest(tgt.address, build_opts=GoBuildOptions())],
    )
    assert maybe_analysis.analysis is not None
    analysis = maybe_analysis.analysis
    assert analysis.cgo_files == ("printer.go",)

    maybe_digest = rule_runner.request(
        FallibleFirstPartyPkgDigest,
        [FirstPartyPkgDigestRequest(tgt.address, build_opts=GoBuildOptions())],
    )
    assert maybe_digest.pkg_digest is not None
    pkg_digest = maybe_digest.pkg_digest

    cgo_request = CGoCompileRequest(
        import_path=analysis.import_path,
        pkg_name=analysis.name,
        digest=pkg_digest.digest,
        build_opts=GoBuildOptions(),
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


def _find_binary(binary_names: Iterable[str]) -> Path | None:
    for path in os.environ["PATH"].split(os.pathsep):
        for gxx_binary_name in binary_names:
            candidate_binary_path = Path(path, gxx_binary_name)
            if candidate_binary_path.exists():
                return candidate_binary_path
    return None


def test_cgo_with_cxx_source(rule_runner: RuleRunner) -> None:
    gxx_path = _find_binary(["clang++", "g++"])
    if gxx_path is None:
        pytest.skip("Skipping test since C++ compiler was not found.")

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
            go_mod(name="mod")
            go_package(name="pkg", sources=["*.go", "*.cxx"])
            go_binary(name="bin")
            """
            ),
            "go.mod": "module example.pantsbuild.org/cgotest\n",
            "print.cxx": dedent(
                r"""\
                #include <iostream>

                extern "C" void do_print(const char * str) {
                    std::cout << str << "\n";
                    std::cout.flush();
                }
                """
            ),
            "main.go": dedent(
                """\
            package main

            // #include <stdlib.h>
            // extern void do_print(const char *);
            import "C"
            import "unsafe"

            func main() {
                cs := C.CString("Hello World!")
                C.do_print(cs)
                C.free(unsafe.Pointer(cs))
            }
            """
            ),
        }
    )

    rule_runner.set_options(
        args=[
            "--golang-cgo-enabled",
            f"--golang-cgo-tool-search-paths=['{str(gxx_path.parent)}']",
            f"--golang-cgo-gxx-binary-name={gxx_path.name}",
        ],
        env_inherit={"PATH"},
    )

    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    maybe_analysis = rule_runner.request(
        FallibleFirstPartyPkgAnalysis,
        [FirstPartyPkgAnalysisRequest(tgt.address, build_opts=GoBuildOptions())],
    )
    assert maybe_analysis.analysis is not None
    analysis = maybe_analysis.analysis
    assert analysis.cgo_files == ("main.go",)
    assert analysis.cxx_files == ("print.cxx",)

    maybe_digest = rule_runner.request(
        FallibleFirstPartyPkgDigest,
        [FirstPartyPkgDigestRequest(tgt.address, build_opts=GoBuildOptions())],
    )
    assert maybe_digest.pkg_digest is not None
    pkg_digest = maybe_digest.pkg_digest

    cgo_request = CGoCompileRequest(
        import_path=analysis.import_path,
        pkg_name=analysis.name,
        digest=pkg_digest.digest,
        build_opts=GoBuildOptions(),
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


@pytest.mark.no_error_if_skipped
def test_cgo_with_objc_source(rule_runner: RuleRunner) -> None:
    gcc_path = _find_binary(["clang", "gcc"])
    if gcc_path is None:
        pytest.skip("Skipping test since C/Objective-C compiler was not found.")

    # This test relies on Foundation library being available. Skip if not on macOS.
    if os.uname().sysname != "Darwin":
        pytest.skip("Skipping Objective-C test because not running on macOS.")

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
            go_mod(name="mod")
            go_package(name="pkg", sources=["*.go", "*.m"])
            go_binary(name="bin")
            """
            ),
            "go.mod": "module example.pantsbuild.org/cgotest\n",
            "print.m": dedent(
                r"""\
                #import <Foundation/Foundation.h>

                void do_print(const char * str) {
                    NSAutoreleasePool * pool = [[NSAutoreleasePool alloc] init];
                    NSLog(@"Got: %s", str);
                    [pool drain];
                }
                """
            ),
            "main.go": dedent(
                """\
            package main

            // #cgo LDFLAGS: -framework Foundation
            // #include <stdlib.h>
            // extern void do_print(const char *);
            import "C"
            import "unsafe"

            func main() {
                cs := C.CString("Hello World!")
                C.do_print(cs)
                C.free(unsafe.Pointer(cs))
            }
            """
            ),
        }
    )

    rule_runner.set_options(
        args=[
            "--golang-cgo-enabled",
            f"--golang-cgo-tool-search-paths=['{str(gcc_path.parent)}']",
            f"--golang-cgo-gcc-binary-name={gcc_path.name}",
        ],
        env_inherit={"PATH"},
    )

    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    maybe_analysis = rule_runner.request(
        FallibleFirstPartyPkgAnalysis,
        [FirstPartyPkgAnalysisRequest(tgt.address, build_opts=GoBuildOptions())],
    )
    assert maybe_analysis.analysis is not None
    analysis = maybe_analysis.analysis
    assert analysis.cgo_files == ("main.go",)
    assert analysis.m_files == ("print.m",)

    maybe_digest = rule_runner.request(
        FallibleFirstPartyPkgDigest,
        [FirstPartyPkgDigestRequest(tgt.address, build_opts=GoBuildOptions())],
    )
    assert maybe_digest.pkg_digest is not None
    pkg_digest = maybe_digest.pkg_digest

    cgo_request = CGoCompileRequest(
        import_path=analysis.import_path,
        pkg_name=analysis.name,
        digest=pkg_digest.digest,
        build_opts=GoBuildOptions(),
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
    assert "Got: Hello World!" in result.stderr.decode()


@pytest.mark.no_error_if_skipped
def test_cgo_with_fortran_source(rule_runner: RuleRunner) -> None:
    # gcc needed for linking
    gcc_path = _find_binary(["clang", "gcc"])
    if gcc_path is None:
        pytest.skip("Skipping test since C compiler was not found.")

    fortran_path = _find_binary(["gfortran"])
    if fortran_path is None:
        pytest.skip("Skipping test since Fortran compiler was not found.")

    # Find the Fortran standard library.
    libgfortran_path = Path(
        subprocess.check_output([str(fortran_path), "-print-file-name=libgfortran.a"])
        .decode()
        .strip()
    )

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
            go_mod(name="mod")
            go_package(name="pkg", sources=["*.go", "*.f90"])
            go_binary(name="bin")
            """
            ),
            "go.mod": "module example.pantsbuild.org/cgotest\n",
            "answer.f90": dedent(
                """\
                function the_answer() result(j) bind(C)
                  use iso_c_binding, only: c_int
                  integer(c_int) :: j ! output
                  j = 42
                end function the_answer
                """
            ),
            "main.go": dedent(
                r"""
            package main

            // extern int the_answer();
            import "C"
            import "fmt"

            func main() {{
                fmt.Printf("Answer: %d\n", C.the_answer())
            }}
            """
            ),
        }
    )

    rule_runner.set_options(
        args=[
            "--golang-cgo-enabled",
            f"--golang-cgo-tool-search-paths=['{str(gcc_path.parent)}', '{str(fortran_path.parent)}']",
            f"--golang-cgo-gcc-binary-name={gcc_path.name}",
            f"--golang-cgo-fortran-binary-name={fortran_path.name}",
            f"--golang-cgo-linker-flags=-L{libgfortran_path.parent}",
        ],
        env_inherit={"PATH"},
    )

    tgt = rule_runner.get_target(Address("", target_name="pkg"))
    maybe_analysis = rule_runner.request(
        FallibleFirstPartyPkgAnalysis,
        [FirstPartyPkgAnalysisRequest(tgt.address, build_opts=GoBuildOptions())],
    )
    assert maybe_analysis.analysis is not None
    analysis = maybe_analysis.analysis
    assert analysis.cgo_files == ("main.go",)
    assert analysis.f_files == ("answer.f90",)

    maybe_digest = rule_runner.request(
        FallibleFirstPartyPkgDigest,
        [FirstPartyPkgDigestRequest(tgt.address, build_opts=GoBuildOptions())],
    )
    assert maybe_digest.pkg_digest is not None
    pkg_digest = maybe_digest.pkg_digest

    cgo_request = CGoCompileRequest(
        import_path=analysis.import_path,
        pkg_name=analysis.name,
        digest=pkg_digest.digest,
        build_opts=GoBuildOptions(),
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
    assert result.stdout.decode() == "Answer: 42\n"


@pytest.mark.no_error_if_skipped
def test_cgo_with_embedded_static_library(rule_runner: RuleRunner) -> None:
    # gcc needed for linking
    gcc_path = _find_binary(["clang", "gcc"])
    if gcc_path is None:
        pytest.skip("Skipping test since C compiler was not found.")

    go_mod_src = pkgutil.get_data(__name__, "cgo_test_mod.sum")
    assert go_mod_src is not None

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
            go_mod(name="mod")
            go_package(name="pkg")
            go_binary(name="bin")
            """
            ),
            "go.mod": dedent(
                """\
                module example.pantsbuild.org/cgotest
                require github.com/confluentinc/confluent-kafka-go/v2 v2.1.0
                """
            ),
            "go.sum": go_mod_src,
            "client.go": dedent(
                r"""
                package main

                import (
                    "fmt"
                    "github.com/confluentinc/confluent-kafka-go/v2/kafka"
                )

                func main() {

                    c, err := kafka.NewConsumer(&kafka.ConfigMap{
                        "bootstrap.servers": "localhost",
                        "group.id":          "myGroup",
                        "auto.offset.reset": "earliest",
                    })

                    if err != nil {
                        panic(err)
                    }

                    c.SubscribeTopics([]string{"myTopic", "^aRegex.*[Tt]opic"}, nil)

                    for {
                        msg, err := c.ReadMessage(-1)
                        if err == nil {
                            fmt.Printf("Message on %s: %s\n", msg.TopicPartition, string(msg.Value))
                        } else {
                            // The client will automatically try to recover from all errors.
                            fmt.Printf("Consumer error: %v (%v)\n", err, msg)
                        }
                    }

                    c.Close()
                }
            """
            ),
        }
    )

    rule_runner.set_options(
        args=[
            "--golang-cgo-enabled",
            f"--golang-cgo-tool-search-paths=['{str(gcc_path.parent)}']",
            f"--golang-cgo-gcc-binary-name={gcc_path.name}",
            f"--golang-external-linker-binary-name={gcc_path.name}",
        ],
        env_inherit={"PATH"},
    )

    tgt = rule_runner.get_target(Address("", target_name="bin"))
    rule_runner.request(BuiltPackage, [GoBinaryFieldSet.create(tgt)])
