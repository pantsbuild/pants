# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
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
            "go.sum": dedent(
                """\
                bazil.org/fuse v0.0.0-20200407214033-5883e5a4b512/go.mod h1:FbcW6z/2VytnFDhZfumh8Ss8zxHE6qpMP5sHTRe0EaM=
                cloud.google.com/go v0.110.0/go.mod h1:SJnCLqQ0FCFGSZMUNUf84MV3Aia54kn7pi8st7tMzaY=
                cloud.google.com/go/accessapproval v1.6.0/go.mod h1:R0EiYnwV5fsRFiKZkPHr6mwyk2wxUJ30nL4j2pcFY2E=
                cloud.google.com/go/accesscontextmanager v1.7.0/go.mod h1:CEGLewx8dwa33aDAZQujl7Dx+uYhS0eay198wB/VumQ=
                cloud.google.com/go/aiplatform v1.36.1/go.mod h1:WTm12vJRPARNvJ+v6P52RDHCNe4AhvjcIZ/9/RRHy/k=
                cloud.google.com/go/analytics v0.19.0/go.mod h1:k8liqf5/HCnOUkbawNtrWWc+UAzyDlW89doe8TtoDsE=
                cloud.google.com/go/apigateway v1.5.0/go.mod h1:GpnZR3Q4rR7LVu5951qfXPJCHquZt02jf7xQx7kpqN8=
                cloud.google.com/go/apigeeconnect v1.5.0/go.mod h1:KFaCqvBRU6idyhSNyn3vlHXc8VMDJdRmwDF6JyFRqZ8=
                cloud.google.com/go/apigeeregistry v0.6.0/go.mod h1:BFNzW7yQVLZ3yj0TKcwzb8n25CFBri51GVGOEUcgQsc=
                cloud.google.com/go/apikeys v0.6.0/go.mod h1:kbpXu5upyiAlGkKrJgQl8A0rKNNJ7dQ377pdroRSSi8=
                cloud.google.com/go/appengine v1.7.0/go.mod h1:eZqpbHFCqRGa2aCdope7eC0SWLV1j0neb/QnMJVWx6A=
                cloud.google.com/go/area120 v0.7.1/go.mod h1:j84i4E1RboTWjKtZVWXPqvK5VHQFJRF2c1Nm69pWm9k=
                cloud.google.com/go/artifactregistry v1.12.0/go.mod h1:o6P3MIvtzTOnmvGagO9v/rOjjA0HmhJ+/6KAXrmYDCI=
                cloud.google.com/go/asset v1.12.0/go.mod h1:h9/sFOa4eDIyKmH6QMpm4eUK3pDojWnUhTgJlk762Hg=
                cloud.google.com/go/assuredworkloads v1.10.0/go.mod h1:kwdUQuXcedVdsIaKgKTp9t0UJkE5+PAVNhdQm4ZVq2E=
                cloud.google.com/go/automl v1.12.0/go.mod h1:tWDcHDp86aMIuHmyvjuKeeHEGq76lD7ZqfGLN6B0NuU=
                cloud.google.com/go/baremetalsolution v0.5.0/go.mod h1:dXGxEkmR9BMwxhzBhV0AioD0ULBmuLZI8CdwalUxuss=
                cloud.google.com/go/batch v0.7.0/go.mod h1:vLZN95s6teRUqRQ4s3RLDsH8PvboqBK+rn1oevL159g=
                cloud.google.com/go/beyondcorp v0.5.0/go.mod h1:uFqj9X+dSfrheVp7ssLTaRHd2EHqSL4QZmH4e8WXGGU=
                cloud.google.com/go/bigquery v1.49.0/go.mod h1:Sv8hMmTFFYBlt/ftw2uN6dFdQPzBlREY9yBh7Oy7/4Q=
                cloud.google.com/go/billing v1.13.0/go.mod h1:7kB2W9Xf98hP9Sr12KfECgfGclsH3CQR0R08tnRlRbc=
                cloud.google.com/go/binaryauthorization v1.5.0/go.mod h1:OSe4OU1nN/VswXKRBmciKpo9LulY41gch5c68htf3/Q=
                cloud.google.com/go/certificatemanager v1.6.0/go.mod h1:3Hh64rCKjRAX8dXgRAyOcY5vQ/fE1sh8o+Mdd6KPgY8=
                cloud.google.com/go/channel v1.12.0/go.mod h1:VkxCGKASi4Cq7TbXxlaBezonAYpp1GCnKMY6tnMQnLU=
                cloud.google.com/go/cloudbuild v1.9.0/go.mod h1:qK1d7s4QlO0VwfYn5YuClDGg2hfmLZEb4wQGAbIgL1s=
                cloud.google.com/go/clouddms v1.5.0/go.mod h1:QSxQnhikCLUw13iAbffF2CZxAER3xDGNHjsTAkQJcQA=
                cloud.google.com/go/cloudtasks v1.10.0/go.mod h1:NDSoTLkZ3+vExFEWu2UJV1arUyzVDAiZtdWcsUyNwBs=
                cloud.google.com/go/compute v1.19.0/go.mod h1:rikpw2y+UMidAe9tISo04EHNOIf42RLYF/q8Bs93scU=
                cloud.google.com/go/compute/metadata v0.2.3/go.mod h1:VAV5nSsACxMJvgaAuX6Pk2AawlZn8kiOGuCv6gTkwuA=
                cloud.google.com/go/contactcenterinsights v1.6.0/go.mod h1:IIDlT6CLcDoyv79kDv8iWxMSTZhLxSCofVV5W6YFM/w=
                cloud.google.com/go/container v1.14.0/go.mod h1:3AoJMPhHfLDxLvrlVWaK57IXzaPnLaZq63WX59aQBfM=
                cloud.google.com/go/containeranalysis v0.9.0/go.mod h1:orbOANbwk5Ejoom+s+DUCTTJ7IBdBQJDcSylAx/on9s=
                cloud.google.com/go/datacatalog v1.13.0/go.mod h1:E4Rj9a5ZtAxcQJlEBTLgMTphfP11/lNaAshpoBgemX8=
                cloud.google.com/go/dataflow v0.8.0/go.mod h1:Rcf5YgTKPtQyYz8bLYhFoIV/vP39eL7fWNcSOyFfLJE=
                cloud.google.com/go/dataform v0.7.0/go.mod h1:7NulqnVozfHvWUBpMDfKMUESr+85aJsC/2O0o3jWPDE=
                cloud.google.com/go/datafusion v1.6.0/go.mod h1:WBsMF8F1RhSXvVM8rCV3AeyWVxcC2xY6vith3iw3S+8=
                cloud.google.com/go/datalabeling v0.7.0/go.mod h1:WPQb1y08RJbmpM3ww0CSUAGweL0SxByuW2E+FU+wXcM=
                cloud.google.com/go/dataplex v1.6.0/go.mod h1:bMsomC/aEJOSpHXdFKFGQ1b0TDPIeL28nJObeO1ppRs=
                cloud.google.com/go/dataproc v1.12.0/go.mod h1:zrF3aX0uV3ikkMz6z4uBbIKyhRITnxvr4i3IjKsKrw4=
                cloud.google.com/go/dataqna v0.7.0/go.mod h1:Lx9OcIIeqCrw1a6KdO3/5KMP1wAmTc0slZWwP12Qq3c=
                cloud.google.com/go/datastore v1.10.0/go.mod h1:PC5UzAmDEkAmkfaknstTYbNpgE49HAgW2J1gcgUfmdM=
                cloud.google.com/go/datastream v1.7.0/go.mod h1:uxVRMm2elUSPuh65IbZpzJNMbuzkcvu5CjMqVIUHrww=
                cloud.google.com/go/deploy v1.8.0/go.mod h1:z3myEJnA/2wnB4sgjqdMfgxCA0EqC3RBTNcVPs93mtQ=
                cloud.google.com/go/dialogflow v1.32.0/go.mod h1:jG9TRJl8CKrDhMEcvfcfFkkpp8ZhgPz3sBGmAUYJ2qE=
                cloud.google.com/go/dlp v1.9.0/go.mod h1:qdgmqgTyReTz5/YNSSuueR8pl7hO0o9bQ39ZhtgkWp4=
                cloud.google.com/go/documentai v1.18.0/go.mod h1:F6CK6iUH8J81FehpskRmhLq/3VlwQvb7TvwOceQ2tbs=
                cloud.google.com/go/domains v0.8.0/go.mod h1:M9i3MMDzGFXsydri9/vW+EWz9sWb4I6WyHqdlAk0idE=
                cloud.google.com/go/edgecontainer v1.0.0/go.mod h1:cttArqZpBB2q58W/upSG++ooo6EsblxDIolxa3jSjbY=
                cloud.google.com/go/errorreporting v0.3.0/go.mod h1:xsP2yaAp+OAW4OIm60An2bbLpqIhKXdWR/tawvl7QzU=
                cloud.google.com/go/essentialcontacts v1.5.0/go.mod h1:ay29Z4zODTuwliK7SnX8E86aUF2CTzdNtvv42niCX0M=
                cloud.google.com/go/eventarc v1.11.0/go.mod h1:PyUjsUKPWoRBCHeOxZd/lbOOjahV41icXyUY5kSTvVY=
                cloud.google.com/go/filestore v1.6.0/go.mod h1:di5unNuss/qfZTw2U9nhFqo8/ZDSc466dre85Kydllg=
                cloud.google.com/go/firestore v1.9.0/go.mod h1:HMkjKHNTtRyZNiMzu7YAsLr9K3X2udY2AMwDaMEQiiE=
                cloud.google.com/go/functions v1.12.0/go.mod h1:AXWGrF3e2C/5ehvwYo/GH6O5s09tOPksiKhz+hH8WkA=
                cloud.google.com/go/gaming v1.9.0/go.mod h1:Fc7kEmCObylSWLO334NcO+O9QMDyz+TKC4v1D7X+Bc0=
                cloud.google.com/go/gkebackup v0.4.0/go.mod h1:byAyBGUwYGEEww7xsbnUTBHIYcOPy/PgUWUtOeRm9Vg=
                cloud.google.com/go/gkeconnect v0.7.0/go.mod h1:SNfmVqPkaEi3bF/B3CNZOAYPYdg7sU+obZ+QTky2Myw=
                cloud.google.com/go/gkehub v0.12.0/go.mod h1:djiIwwzTTBrF5NaXCGv3mf7klpEMcST17VBTVVDcuaw=
                cloud.google.com/go/gkemulticloud v0.5.0/go.mod h1:W0JDkiyi3Tqh0TJr//y19wyb1yf8llHVto2Htf2Ja3Y=
                cloud.google.com/go/grafeas v0.2.0/go.mod h1:KhxgtF2hb0P191HlY5besjYm6MqTSTj3LSI+M+ByZHc=
                cloud.google.com/go/gsuiteaddons v1.5.0/go.mod h1:TFCClYLd64Eaa12sFVmUyG62tk4mdIsI7pAnSXRkcFo=
                cloud.google.com/go/iam v0.13.0/go.mod h1:ljOg+rcNfzZ5d6f1nAUJ8ZIxOaZUVoS14bKCtaLZ/D0=
                cloud.google.com/go/iap v1.7.0/go.mod h1:beqQx56T9O1G1yNPph+spKpNibDlYIiIixiqsQXxLIo=
                cloud.google.com/go/ids v1.3.0/go.mod h1:JBdTYwANikFKaDP6LtW5JAi4gubs57SVNQjemdt6xV4=
                cloud.google.com/go/iot v1.6.0/go.mod h1:IqdAsmE2cTYYNO1Fvjfzo9po179rAtJeVGUvkLN3rLE=
                cloud.google.com/go/kms v1.10.0/go.mod h1:ng3KTUtQQU9bPX3+QGLsflZIHlkbn8amFAMY63m8d24=
                cloud.google.com/go/language v1.9.0/go.mod h1:Ns15WooPM5Ad/5no/0n81yUetis74g3zrbeJBE+ptUY=
                cloud.google.com/go/lifesciences v0.8.0/go.mod h1:lFxiEOMqII6XggGbOnKiyZ7IBwoIqA84ClvoezaA/bo=
                cloud.google.com/go/logging v1.7.0/go.mod h1:3xjP2CjkM3ZkO73aj4ASA5wRPGGCRrPIAeNqVNkzY8M=
                cloud.google.com/go/longrunning v0.4.1/go.mod h1:4iWDqhBZ70CvZ6BfETbvam3T8FMvLK+eFj0E6AaRQTo=
                cloud.google.com/go/managedidentities v1.5.0/go.mod h1:+dWcZ0JlUmpuxpIDfyP5pP5y0bLdRwOS4Lp7gMni/LA=
                cloud.google.com/go/maps v0.7.0/go.mod h1:3GnvVl3cqeSvgMcpRlQidXsPYuDGQ8naBis7MVzpXsY=
                cloud.google.com/go/mediatranslation v0.7.0/go.mod h1:LCnB/gZr90ONOIQLgSXagp8XUW1ODs2UmUMvcgMfI2I=
                cloud.google.com/go/memcache v1.9.0/go.mod h1:8oEyzXCu+zo9RzlEaEjHl4KkgjlNDaXbCQeQWlzNFJM=
                cloud.google.com/go/metastore v1.10.0/go.mod h1:fPEnH3g4JJAk+gMRnrAnoqyv2lpUCqJPWOodSaf45Eo=
                cloud.google.com/go/monitoring v1.13.0/go.mod h1:k2yMBAB1H9JT/QETjNkgdCGD9bPF712XiLTVr+cBrpw=
                cloud.google.com/go/networkconnectivity v1.11.0/go.mod h1:iWmDD4QF16VCDLXUqvyspJjIEtBR/4zq5hwnY2X3scM=
                cloud.google.com/go/networkmanagement v1.6.0/go.mod h1:5pKPqyXjB/sgtvB5xqOemumoQNB7y95Q7S+4rjSOPYY=
                cloud.google.com/go/networksecurity v0.8.0/go.mod h1:B78DkqsxFG5zRSVuwYFRZ9Xz8IcQ5iECsNrPn74hKHU=
                cloud.google.com/go/notebooks v1.8.0/go.mod h1:Lq6dYKOYOWUCTvw5t2q1gp1lAp0zxAxRycayS0iJcqQ=
                cloud.google.com/go/optimization v1.3.1/go.mod h1:IvUSefKiwd1a5p0RgHDbWCIbDFgKuEdB+fPPuP0IDLI=
                cloud.google.com/go/orchestration v1.6.0/go.mod h1:M62Bevp7pkxStDfFfTuCOaXgaaqRAga1yKyoMtEoWPQ=
                cloud.google.com/go/orgpolicy v1.10.0/go.mod h1:w1fo8b7rRqlXlIJbVhOMPrwVljyuW5mqssvBtU18ONc=
                cloud.google.com/go/osconfig v1.11.0/go.mod h1:aDICxrur2ogRd9zY5ytBLV89KEgT2MKB2L/n6x1ooPw=
                cloud.google.com/go/oslogin v1.9.0/go.mod h1:HNavntnH8nzrn8JCTT5fj18FuJLFJc4NaZJtBnQtKFs=
                cloud.google.com/go/phishingprotection v0.7.0/go.mod h1:8qJI4QKHoda/sb/7/YmMQ2omRLSLYSu9bU0EKCNI+Lk=
                cloud.google.com/go/policytroubleshooter v1.6.0/go.mod h1:zYqaPTsmfvpjm5ULxAyD/lINQxJ0DDsnWOP/GZ7xzBc=
                cloud.google.com/go/privatecatalog v0.8.0/go.mod h1:nQ6pfaegeDAq/Q5lrfCQzQLhubPiZhSaNhIgfJlnIXs=
                cloud.google.com/go/pubsub v1.30.0/go.mod h1:qWi1OPS0B+b5L+Sg6Gmc9zD1Y+HaM0MdUr7LsupY1P4=
                cloud.google.com/go/pubsublite v1.7.0/go.mod h1:8hVMwRXfDfvGm3fahVbtDbiLePT3gpoiJYJY+vxWxVM=
                cloud.google.com/go/recaptchaenterprise v1.3.1/go.mod h1:OdD+q+y4XGeAlxRaMn1Y7/GveP6zmq76byL6tjPE7d4=
                cloud.google.com/go/recaptchaenterprise/v2 v2.7.0/go.mod h1:19wVj/fs5RtYtynAPJdDTb69oW0vNHYDBTbB4NvMD9c=
                cloud.google.com/go/recommendationengine v0.7.0/go.mod h1:1reUcE3GIu6MeBz/h5xZJqNLuuVjNg1lmWMPyjatzac=
                cloud.google.com/go/recommender v1.9.0/go.mod h1:PnSsnZY7q+VL1uax2JWkt/UegHssxjUVVCrX52CuEmQ=
                cloud.google.com/go/redis v1.11.0/go.mod h1:/X6eicana+BWcUda5PpwZC48o37SiFVTFSs0fWAJ7uQ=
                cloud.google.com/go/resourcemanager v1.6.0/go.mod h1:YcpXGRs8fDzcUl1Xw8uOVmI8JEadvhRIkoXXUNVYcVo=
                cloud.google.com/go/resourcesettings v1.5.0/go.mod h1:+xJF7QSG6undsQDfsCJyqWXyBwUoJLhetkRMDRnIoXA=
                cloud.google.com/go/retail v1.12.0/go.mod h1:UMkelN/0Z8XvKymXFbD4EhFJlYKRx1FGhQkVPU5kF14=
                cloud.google.com/go/run v0.9.0/go.mod h1:Wwu+/vvg8Y+JUApMwEDfVfhetv30hCG4ZwDR/IXl2Qg=
                cloud.google.com/go/scheduler v1.9.0/go.mod h1:yexg5t+KSmqu+njTIh3b7oYPheFtBWGcbVUYF1GGMIc=
                cloud.google.com/go/secretmanager v1.10.0/go.mod h1:MfnrdvKMPNra9aZtQFvBcvRU54hbPD8/HayQdlUgJpU=
                cloud.google.com/go/security v1.13.0/go.mod h1:Q1Nvxl1PAgmeW0y3HTt54JYIvUdtcpYKVfIB8AOMZ+0=
                cloud.google.com/go/securitycenter v1.19.0/go.mod h1:LVLmSg8ZkkyaNy4u7HCIshAngSQ8EcIRREP3xBnyfag=
                cloud.google.com/go/servicecontrol v1.11.1/go.mod h1:aSnNNlwEFBY+PWGQ2DoM0JJ/QUXqV5/ZD9DOLB7SnUk=
                cloud.google.com/go/servicedirectory v1.9.0/go.mod h1:29je5JjiygNYlmsGz8k6o+OZ8vd4f//bQLtvzkPPT/s=
                cloud.google.com/go/servicemanagement v1.8.0/go.mod h1:MSS2TDlIEQD/fzsSGfCdJItQveu9NXnUniTrq/L8LK4=
                cloud.google.com/go/serviceusage v1.6.0/go.mod h1:R5wwQcbOWsyuOfbP9tGdAnCAc6B9DRwPG1xtWMDeuPA=
                cloud.google.com/go/shell v1.6.0/go.mod h1:oHO8QACS90luWgxP3N9iZVuEiSF84zNyLytb+qE2f9A=
                cloud.google.com/go/spanner v1.44.0/go.mod h1:G8XIgYdOK+Fbcpbs7p2fiprDw4CaZX63whnSMLVBxjk=
                cloud.google.com/go/speech v1.15.0/go.mod h1:y6oH7GhqCaZANH7+Oe0BhgIogsNInLlz542tg3VqeYI=
                cloud.google.com/go/storage v1.29.0/go.mod h1:4puEjyTKnku6gfKoTfNOU/W+a9JyuVNxjpS5GBrB8h4=
                cloud.google.com/go/storagetransfer v1.8.0/go.mod h1:JpegsHHU1eXg7lMHkvf+KE5XDJ7EQu0GwNJbbVGanEw=
                cloud.google.com/go/talent v1.5.0/go.mod h1:G+ODMj9bsasAEJkQSzO2uHQWXHHXUomArjWQQYkqK6c=
                cloud.google.com/go/texttospeech v1.6.0/go.mod h1:YmwmFT8pj1aBblQOI3TfKmwibnsfvhIBzPXcW4EBovc=
                cloud.google.com/go/tpu v1.5.0/go.mod h1:8zVo1rYDFuW2l4yZVY0R0fb/v44xLh3llq7RuV61fPM=
                cloud.google.com/go/trace v1.9.0/go.mod h1:lOQqpE5IaWY0Ixg7/r2SjixMuc6lfTFeO4QGM4dQWOk=
                cloud.google.com/go/translate v1.7.0/go.mod h1:lMGRudH1pu7I3n3PETiOB2507gf3HnfLV8qlkHZEyos=
                cloud.google.com/go/video v1.14.0/go.mod h1:SkgaXwT+lIIAKqWAJfktHT/RbgjSuY6DobxEp0C5yTQ=
                cloud.google.com/go/videointelligence v1.10.0/go.mod h1:LHZngX1liVtUhZvi2uNS0VQuOzNi2TkY1OakiuoUOjU=
                cloud.google.com/go/vision v1.2.0/go.mod h1:SmNwgObm5DpFBme2xpyOyasvBc1aPdjvMk2bBk0tKD0=
                cloud.google.com/go/vision/v2 v2.7.0/go.mod h1:H89VysHy21avemp6xcf9b9JvZHVehWbET0uT/bcuY/0=
                cloud.google.com/go/vmmigration v1.6.0/go.mod h1:bopQ/g4z+8qXzichC7GW1w2MjbErL54rk3/C843CjfY=
                cloud.google.com/go/vmwareengine v0.3.0/go.mod h1:wvoyMvNWdIzxMYSpH/R7y2h5h3WFkx6d+1TIsP39WGY=
                cloud.google.com/go/vpcaccess v1.6.0/go.mod h1:wX2ILaNhe7TlVa4vC5xce1bCnqE3AeH27RV31lnmZes=
                cloud.google.com/go/webrisk v1.8.0/go.mod h1:oJPDuamzHXgUc+b8SiHRcVInZQuybnvEW72PqTc7sSg=
                cloud.google.com/go/websecurityscanner v1.5.0/go.mod h1:Y6xdCPy81yi0SQnDY1xdNTNpfY1oAgXUlcfN3B3eSng=
                cloud.google.com/go/workflows v1.10.0/go.mod h1:fZ8LmRmZQWacon9UCX1r/g/DfAXx5VcPALq2CxzdePw=
                dmitri.shuralyov.com/gpu/mtl v0.0.0-20190408044501-666a987793e9/go.mod h1:H6x//7gZCb22OMCxBHrMx7a5I7Hp++hsVxbQ4BYO7hU=
                gioui.org v0.0.0-20210308172011-57750fc8a0a6/go.mod h1:RSH6KIUZ0p2xy5zHDxgAM4zumjgTw83q2ge/PI+yyw8=
                git.sr.ht/~sbinet/gg v0.3.1/go.mod h1:KGYtlADtqsqANL9ueOFkWymvzUvLMQllU5Ixo+8v3pc=
                github.com/AdaLogics/go-fuzz-headers v0.0.0-20210715213245-6c3934b029d8/go.mod h1:CzsSbkDixRphAF5hS6wbMKq0eI6ccJRb7/A0M6JBnwg=
                github.com/Azure/azure-sdk-for-go v16.2.1+incompatible/go.mod h1:9XXNKU+eRnpl9moKnB4QOLf1HestfXbmab5FXxiDBjc=
                github.com/Azure/go-ansiterm v0.0.0-20210617225240-d185dfc1b5a1/go.mod h1:xomTg63KZ2rFqZQzSB4Vz2SUXa1BpHTVz9L5PTmPC4E=
                github.com/Azure/go-autorest v14.2.0+incompatible/go.mod h1:r+4oMnoxhatjLLJ6zxSWATqVooLgysK6ZNox3g/xq24=
                github.com/Azure/go-autorest/autorest v0.11.18/go.mod h1:dSiJPy22c3u0OtOKDNttNgqpNFY/GeWa7GH/Pz56QRA=
                github.com/Azure/go-autorest/autorest/adal v0.9.13/go.mod h1:W/MM4U6nLxnIskrw4UwWzlHfGjwUS50aOsc/I3yuU8M=
                github.com/Azure/go-autorest/autorest/date v0.3.0/go.mod h1:BI0uouVdmngYNUzGWeSYnokU+TrmwEsOqdt8Y6sso74=
                github.com/Azure/go-autorest/autorest/mocks v0.4.1/go.mod h1:LTp+uSrOhSkaKrUy935gNZuuIPPVsHlr9DSOxSayd+k=
                github.com/Azure/go-autorest/logger v0.2.1/go.mod h1:T9E3cAhj2VqvPOtCYAvby9aBXkZmbF5NWuPV8+WeEW8=
                github.com/Azure/go-autorest/tracing v0.6.0/go.mod h1:+vhtPC754Xsa23ID7GlGsrdKBpUA79WCAKPPZVC2DeU=
                github.com/BurntSushi/toml v0.3.1/go.mod h1:xHWCNGjB5oqiDr8zfno3MHue2Ht5sIBksp03qcyfWMU=
                github.com/BurntSushi/xgb v0.0.0-20160522181843-27f122750802/go.mod h1:IVnqGOEym/WlBOVXweHU+Q+/VP0lqqI8lqeDx9IjBqo=
                github.com/JohnCGriffin/overflow v0.0.0-20211019200055-46fa312c352c/go.mod h1:X0CRv0ky0k6m906ixxpzmDRLvX58TFUKS2eePweuyxk=
                github.com/Microsoft/go-winio v0.5.2/go.mod h1:WpS1mjBmmwHBEWmogvA2mj8546UReBk4v8QkMxJ6pZY=
                github.com/Microsoft/hcsshim v0.9.4/go.mod h1:7pLA8lDk46WKDWlVsENo92gC0XFa8rbKfyFRBqxEbCc=
                github.com/Microsoft/hcsshim/test v0.0.0-20210227013316-43a75bb4edd3/go.mod h1:mw7qgWloBUl75W/gVH3cQszUg1+gUITj7D6NY7ywVnY=
                github.com/NYTimes/gziphandler v1.1.1/go.mod h1:n/CVRwUEOgIxrgPvAQhUUr9oeUtvrhMomdKFjzJNB0c=
                github.com/OneOfOne/xxhash v1.2.2/go.mod h1:HSdplMjZKSmBqAxg5vPj2TmRDmfkzw+cTzAElWljhcU=
                github.com/PuerkitoBio/purell v1.1.1/go.mod h1:c11w/QuzBsJSee3cPx9rAFu61PvFxuPbtSwDGJws/X0=
                github.com/PuerkitoBio/urlesc v0.0.0-20170810143723-de5bf2ad4578/go.mod h1:uGdkoq3SwY9Y+13GIhn11/XLaGBb4BfwItxLd5jeuXE=
                github.com/Shopify/logrus-bugsnag v0.0.0-20171204204709-577dee27f20d/go.mod h1:HI8ITrYtUY+O+ZhtlqUnD8+KwNPOyugEhfP9fdUIaEQ=
                github.com/actgardner/gogen-avro/v10 v10.2.1/go.mod h1:QUhjeHPchheYmMDni/Nx7VB0RsT/ee8YIgGY/xpEQgQ=
                github.com/ajstarks/deck v0.0.0-20200831202436-30c9fc6549a9/go.mod h1:JynElWSGnm/4RlzPXRlREEwqTHAN3T56Bv2ITsFT3gY=
                github.com/ajstarks/deck/generate v0.0.0-20210309230005-c3f852c02e19/go.mod h1:T13YZdzov6OU0A1+RfKZiZN9ca6VeKdBdyDV+BY97Tk=
                github.com/ajstarks/svgo v0.0.0-20211024235047-1546f124cd8b/go.mod h1:1KcenG0jGWcpt8ov532z81sp/kMMUG485J2InIOyADM=
                github.com/alecthomas/template v0.0.0-20190718012654-fb15b899a751/go.mod h1:LOuyumcjzFXgccqObfd/Ljyb9UuFJ6TxHnclSeseNhc=
                github.com/alecthomas/units v0.0.0-20190924025748-f65c72e2690d/go.mod h1:rBZYJk541a8SKzHPHnH3zbiI+7dagKZ0cgpgrD7Fyho=
                github.com/alexflint/go-filemutex v1.1.0/go.mod h1:7P4iRhttt/nUvUOrYIhcpMzv2G6CY9UnI16Z+UJqRyk=
                github.com/andybalholm/brotli v1.0.4/go.mod h1:fO7iG3H7G2nSZ7m0zPUDn85XEX2GTukHGRSepvi9Eig=
                github.com/antihax/optional v1.0.0/go.mod h1:uupD/76wgC+ih3iEmQUL+0Ugr19nfwCT1kdvxnR2qWY=
                github.com/apache/arrow/go/v10 v10.0.1/go.mod h1:YvhnlEePVnBS4+0z3fhPfUy7W1Ikj0Ih0vcRo/gZ1M0=
                github.com/apache/arrow/go/v11 v11.0.0/go.mod h1:Eg5OsL5H+e299f7u5ssuXsuHQVEGC4xei5aX110hRiI=
                github.com/apache/thrift v0.16.0/go.mod h1:PHK3hniurgQaNMZYaCLEqXKsYK8upmhPbmdP2FXSqgU=
                github.com/armon/circbuf v0.0.0-20150827004946-bbbad097214e/go.mod h1:3U/XgcO3hCbHZ8TKRvWD2dDTCfh9M9ya+I9JpbB7O8o=
                github.com/armon/consul-api v0.0.0-20180202201655-eb2c6b5be1b6/go.mod h1:grANhF5doyWs3UAsr3K4I6qtAmlQcZDesFNEHPZAzj8=
                github.com/armon/go-metrics v0.0.0-20180917152333-f0300d1749da/go.mod h1:Q73ZrmVTwzkszR9V5SSuryQ31EELlFMUz1kKyl939pY=
                github.com/armon/go-radix v0.0.0-20180808171621-7fddfc383310/go.mod h1:ufUuZ+zHj4x4TnLV4JWEpy2hxWSpsRywHrMgIH9cCH8=
                github.com/asaskevich/govalidator v0.0.0-20190424111038-f61b66f89f4a/go.mod h1:lB+ZfQJz7igIIfQNfa7Ml4HSf2uFQQRzpGGRXenZAgY=
                github.com/aws/aws-sdk-go v1.15.11/go.mod h1:mFuSZ37Z9YOHbQEwBWztmVzqXrEkub65tZoCYDt7FT0=
                github.com/benbjohnson/clock v1.0.3/go.mod h1:bGMdMPoPVvcYyt1gHDf4J2KE153Yf9BuiUKYMaxlTDM=
                github.com/beorn7/perks v1.0.1/go.mod h1:G2ZrVWU2WbWT9wwq4/hrbKbnv/1ERSJQ0ibhJ6rlkpw=
                github.com/bgentry/speakeasy v0.1.0/go.mod h1:+zsyZBPWlz7T6j88CTgSN5bM796AkVf0kBD4zp0CCIs=
                github.com/bitly/go-simplejson v0.5.0/go.mod h1:cXHtHw4XUPsvGaxgjIAn8PhEWG9NfngEKAMDJEczWVA=
                github.com/bits-and-blooms/bitset v1.2.0/go.mod h1:gIdJ4wp64HaoK2YrL1Q5/N7Y16edYb8uY+O0FJTyyDA=
                github.com/bketelsen/crypt v0.0.3-0.20200106085610-5cbc8cc4026c/go.mod h1:MKsuJmJgSg28kpZDP6UIiPt0e0Oz0kqKNGyRaWEPv84=
                github.com/blang/semver v3.5.1+incompatible/go.mod h1:kRBLl5iJ+tD4TcOOxsy/0fnwebNt5EWlYSAyrTnjyyk=
                github.com/bmizerany/assert v0.0.0-20160611221934-b7ed37b82869/go.mod h1:Ekp36dRnpXw/yCqJaO+ZrUyxD+3VXMFFr56k5XYrpB4=
                github.com/boombuler/barcode v1.0.1/go.mod h1:paBWMcWSl3LHKBqUq+rly7CNSldXjb2rDl3JlRe0mD8=
                github.com/bshuster-repo/logrus-logstash-hook v0.4.1/go.mod h1:zsTqEiSzDgAa/8GZR7E1qaXrhYNDKBYy5/dWPTIflbk=
                github.com/buger/jsonparser v1.1.1/go.mod h1:6RYKKt7H4d4+iWqouImQ9R2FZql3VbhNgx27UK13J/0=
                github.com/bugsnag/bugsnag-go v0.0.0-20141110184014-b1d153021fcd/go.mod h1:2oa8nejYd4cQ/b0hMIopN0lCRxU0bueqREvZLWFrtK8=
                github.com/bugsnag/osext v0.0.0-20130617224835-0dd3f918b21b/go.mod h1:obH5gd0BsqsP2LwDJ9aOkm/6J86V6lyAXCoQWGw3K50=
                github.com/bugsnag/panicwrap v0.0.0-20151223152923-e2c28503fcd0/go.mod h1:D/8v3kj0zr8ZAKg1AQ6crr+5VwKN5eIywRkfhyM/+dE=
                github.com/cenkalti/backoff/v4 v4.1.3/go.mod h1:scbssz8iZGpm3xbr14ovlUdkxfGXNInqkPWOWmG2CLw=
                github.com/census-instrumentation/opencensus-proto v0.4.1/go.mod h1:4T9NM4+4Vw91VeyqjLS6ao50K5bOcLKN6Q42XnYaRYw=
                github.com/certifi/gocertifi v0.0.0-20200922220541-2c3bb06c6054/go.mod h1:sGbDF6GwGcLpkNXPUTkMRoywsNa/ol15pxFe6ERfguA=
                github.com/cespare/xxhash v1.1.0/go.mod h1:XrSqR1VqqWfGrhpAt58auRo0WTKS1nRRg3ghfAqPWnc=
                github.com/cespare/xxhash/v2 v2.2.0/go.mod h1:VGX0DQ3Q6kWi7AoAeZDth3/j3BFtOZR5XLFGgcrjCOs=
                github.com/checkpoint-restore/go-criu/v4 v4.1.0/go.mod h1:xUQBLp4RLc5zJtWY++yjOoMoB5lihDt7fai+75m+rGw=
                github.com/checkpoint-restore/go-criu/v5 v5.3.0/go.mod h1:E/eQpaFtUKGOOSEBZgmKAcn+zUUwWxqcaKZlF54wK8E=
                github.com/chzyer/logex v1.1.10/go.mod h1:+Ywpsq7O8HXn0nuIou7OrIPyXbp3wmkHB+jjWRnGsAI=
                github.com/chzyer/readline v0.0.0-20180603132655-2972be24d48e/go.mod h1:nSuG5e5PlCu98SY8svDHJxuZscDgtXS6KTTbou5AhLI=
                github.com/chzyer/test v0.0.0-20180213035817-a1ea475d72b1/go.mod h1:Q3SI9o4m/ZMnBNeIyt5eFwwo7qiLfzFZmjNmxjkiQlU=
                github.com/cilium/ebpf v0.7.0/go.mod h1:/oI2+1shJiTGAMgl6/RgJr36Eo1jzrRcAWbcXO2usCA=
                github.com/client9/misspell v0.3.4/go.mod h1:qj6jICC3Q7zFZvVWo7KLAzC3yx5G7kyvSDkc90ppPyw=
                github.com/cncf/udpa/go v0.0.0-20220112060539-c52dc94e7fbe/go.mod h1:6pvJx4me5XPnfI9Z40ddWsdw2W/uZgQLFXToKeRcDiI=
                github.com/cncf/xds/go v0.0.0-20230105202645-06c439db220b/go.mod h1:eXthEFrGJvWHgFFCl3hGmgk+/aYT6PnTQLykKQRLhEs=
                github.com/cockroachdb/datadriven v0.0.0-20200714090401-bf6692d28da5/go.mod h1:h6jFvWxBdQXxjopDMZyH2UVceIRfR84bdzbkoKrsWNo=
                github.com/cockroachdb/errors v1.2.4/go.mod h1:rQD95gz6FARkaKkQXUksEje/d9a6wBJoCr5oaCLELYA=
                github.com/cockroachdb/logtags v0.0.0-20190617123548-eb05cc24525f/go.mod h1:i/u985jwjWRlyHXQbwatDASoW0RMlZ/3i9yJHE2xLkI=
                github.com/confluentinc/confluent-kafka-go/v2 v2.1.0 h1:FLUBKRb0V9+JauKMUq1lt19YIMM4djhjV1+6szFWmuw=
                github.com/confluentinc/confluent-kafka-go/v2 v2.1.0/go.mod h1:mfGzHbxQ6LRc25qqaLotDHkhdYmeZQ3ctcKNlPUjDW4=
                github.com/containerd/aufs v1.0.0/go.mod h1:kL5kd6KM5TzQjR79jljyi4olc1Vrx6XBlcyj3gNv2PU=
                github.com/containerd/btrfs v1.0.0/go.mod h1:zMcX3qkXTAi9GI50+0HOeuV8LU2ryCE/V2vG/ZBiTss=
                github.com/containerd/cgroups v1.0.4/go.mod h1:nLNQtsF7Sl2HxNebu77i1R0oDlhiTG+kO4JTrUzo6IA=
                github.com/containerd/console v1.0.3/go.mod h1:7LqA/THxQ86k76b8c/EMSiaJ3h1eZkMkXar0TQ1gf3U=
                github.com/containerd/containerd v1.6.8/go.mod h1:By6p5KqPK0/7/CgO/A6t/Gz+CUYUu2zf1hUaaymVXB0=
                github.com/containerd/continuity v0.3.0/go.mod h1:wJEAIwKOm/pBZuBd0JmeTvnLquTB1Ag8espWhkykbPM=
                github.com/containerd/fifo v1.0.0/go.mod h1:ocF/ME1SX5b1AOlWi9r677YJmCPSwwWnQ9O123vzpE4=
                github.com/containerd/go-cni v1.1.6/go.mod h1:BWtoWl5ghVymxu6MBjg79W9NZrCRyHIdUtk4cauMe34=
                github.com/containerd/go-runc v1.0.0/go.mod h1:cNU0ZbCgCQVZK4lgG3P+9tn9/PaJNmoDXPpoJhDR+Ok=
                github.com/containerd/imgcrypt v1.1.4/go.mod h1:LorQnPtzL/T0IyCeftcsMEO7AqxUDbdO8j/tSUpgxvo=
                github.com/containerd/nri v0.1.0/go.mod h1:lmxnXF6oMkbqs39FiCt1s0R2HSMhcLel9vNL3m4AaeY=
                github.com/containerd/stargz-snapshotter/estargz v0.4.1/go.mod h1:x7Q9dg9QYb4+ELgxmo4gBUeJB0tl5dqH1Sdz0nJU1QM=
                github.com/containerd/ttrpc v1.1.0/go.mod h1:XX4ZTnoOId4HklF4edwc4DcqskFZuvXB1Evzy5KFQpQ=
                github.com/containerd/typeurl v1.0.2/go.mod h1:9trJWW2sRlGub4wZJRTW83VtbOLS6hwcDZXTn6oPz9s=
                github.com/containerd/zfs v1.0.0/go.mod h1:m+m51S1DvAP6r3FcmYCp54bQ34pyOwTieQDNRIRHsFY=
                github.com/containernetworking/cni v1.1.1/go.mod h1:sDpYKmGVENF3s6uvMvGgldDWeG8dMxakj/u+i9ht9vw=
                github.com/containernetworking/plugins v1.1.1/go.mod h1:Sr5TH/eBsGLXK/h71HeLfX19sZPp3ry5uHSkI4LPxV8=
                github.com/containers/ocicrypt v1.1.3/go.mod h1:xpdkbVAuaH3WzbEabUd5yDsl9SwJA5pABH85425Es2g=
                github.com/coreos/bbolt v1.3.2/go.mod h1:iRUV2dpdMOn7Bo10OQBFzIJO9kkE559Wcmn+qkEiiKk=
                github.com/coreos/etcd v3.3.13+incompatible/go.mod h1:uF7uidLiAD3TWHmW31ZFd/JWoc32PjwdhPthX9715RE=
                github.com/coreos/go-iptables v0.6.0/go.mod h1:Qe8Bv2Xik5FyTXwgIbLAnv2sWSBmvWdFETJConOQ//Q=
                github.com/coreos/go-oidc v2.1.0+incompatible/go.mod h1:CgnwVTmzoESiwO9qyAFEMiHoZ1nMCKZlZ9V6mm3/LKc=
                github.com/coreos/go-semver v0.3.0/go.mod h1:nnelYz7RCh+5ahJtPPxZlU+153eP4D4r3EedlOD2RNk=
                github.com/coreos/go-systemd v0.0.0-20190321100706-95778dfbb74e/go.mod h1:F5haX7vjVVG0kc13fIWeqUViNPyEJxv/OmvnBo0Yme4=
                github.com/coreos/go-systemd/v22 v22.3.2/go.mod h1:Y58oyj3AT4RCenI/lSvhwexgC+NSVTIJ3seZv2GcEnc=
                github.com/coreos/pkg v0.0.0-20180928190104-399ea9e2e55f/go.mod h1:E3G3o1h8I7cfcXa63jLwjI0eiQQMgzzUDFVpN/nH/eA=
                github.com/cpuguy83/go-md2man/v2 v2.0.0/go.mod h1:maD7wRr/U5Z6m/iR4s+kqSMx2CaBsrgA7czyZG/E6dU=
                github.com/creack/pty v1.1.11/go.mod h1:oKZEueFk5CKHvIhNR5MUki03XCEU+Q6VDXinZuGJ33E=
                github.com/cyphar/filepath-securejoin v0.2.3/go.mod h1:aPGpWjXOXUn2NCNjFvBE6aRxGGx79pTxQpKOJNYHHl4=
                github.com/d2g/dhcp4 v0.0.0-20170904100407-a1d1b6c41b1c/go.mod h1:Ct2BUK8SB0YC1SMSibvLzxjeJLnrYEVLULFNiHY9YfQ=
                github.com/d2g/dhcp4client v1.0.0/go.mod h1:j0hNfjhrt2SxUOw55nL0ATM/z4Yt3t2Kd1mW34z5W5s=
                github.com/d2g/dhcp4server v0.0.0-20181031114812-7d4a0a7f59a5/go.mod h1:Eo87+Kg/IX2hfWJfwxMzLyuSZyxSoAug2nGa1G2QAi8=
                github.com/d2g/hardwareaddr v0.0.0-20190221164911-e7d9fbe030e4/go.mod h1:bMl4RjIciD2oAxI7DmWRx6gbeqrkoLqv3MV0vzNad+I=
                github.com/davecgh/go-spew v1.1.1/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
                github.com/denverdino/aliyungo v0.0.0-20190125010748-a747050bb1ba/go.mod h1:dV8lFg6daOBZbT6/BDGIz6Y3WFGn8juu6G+CQ6LHtl0=
                github.com/dgrijalva/jwt-go v3.2.0+incompatible/go.mod h1:E3ru+11k8xSBh+hMPgOLZmtrrCbhqsmaPHjLKYnJCaQ=
                github.com/dgryski/go-rendezvous v0.0.0-20200823014737-9f7001d12a5f/go.mod h1:cuUVRXasLTGF7a8hSLbxyZXjz+1KgoB3wDUb6vlszIc=
                github.com/dgryski/go-sip13 v0.0.0-20181026042036-e10d5fee7954/go.mod h1:vAd38F8PWV+bWy6jNmig1y/TA+kYO4g3RSRF0IAv0no=
                github.com/dnaeon/go-vcr v1.0.1/go.mod h1:aBB1+wY4s93YsC3HHjMBMrwTj2R9FHDzUr9KyGc8n1E=
                github.com/dnephin/pflag v1.0.7/go.mod h1:uxE91IoWURlOiTUIA8Mq5ZZkAv3dPUfZNaT80Zm7OQE=
                github.com/docker/cli v0.0.0-20191017083524-a8ff7f821017/go.mod h1:JLrzqnKDaYBop7H2jaqPtU4hHvMKP+vjCwu2uszcLI8=
                github.com/docker/distribution v2.8.1+incompatible/go.mod h1:J2gT2udsDAN96Uj4KfcMRqY0/ypR+oyYUYmja8H+y+w=
                github.com/docker/docker v20.10.17+incompatible/go.mod h1:eEKB0N0r5NX/I1kEveEz05bcu8tLC/8azJZsviup8Sk=
                github.com/docker/docker-credential-helpers v0.6.3/go.mod h1:WRaJzqw3CTB9bk10avuGsjVBZsD05qeibJ1/TYlvc0Y=
                github.com/docker/go-connections v0.4.0/go.mod h1:Gbd7IOopHjR8Iph03tsViu4nIes5XhDvyHbTtUxmeec=
                github.com/docker/go-events v0.0.0-20190806004212-e31b211e4f1c/go.mod h1:Uw6UezgYA44ePAFQYUehOuCzmy5zmg/+nl2ZfMWGkpA=
                github.com/docker/go-metrics v0.0.1/go.mod h1:cG1hvH2utMXtqgqqYE9plW6lDxS3/5ayHzueweSI3Vw=
                github.com/docker/go-units v0.5.0/go.mod h1:fgPhTUdO+D/Jk86RDLlptpiXQzgHJF7gydDDbaIK4Dk=
                github.com/docker/libtrust v0.0.0-20150114040149-fa567046d9b1/go.mod h1:cyGadeNEkKy96OOhEzfZl+yxihPEzKnqJwvfuSUqbZE=
                github.com/docker/spdystream v0.0.0-20160310174837-449fdfce4d96/go.mod h1:Qh8CwZgvJUkLughtfhJv5dyTYa91l1fOUCrgjqmcifM=
                github.com/docopt/docopt-go v0.0.0-20180111231733-ee0de3bc6815/go.mod h1:WwZ+bS3ebgob9U8Nd0kOddGdZWjyMGR8Wziv+TBNwSE=
                github.com/dustin/go-humanize v1.0.0/go.mod h1:HtrtbFcZ19U5GC7JDqmcUSB87Iq5E25KnS6fMYU6eOk=
                github.com/elazarl/goproxy v0.0.0-20180725130230-947c36da3153/go.mod h1:/Zj4wYkgs4iZTTu3o/KG3Itv/qCCa8VVMlb3i9OVuzc=
                github.com/emicklei/go-restful v2.9.5+incompatible/go.mod h1:otzb+WCGbkyDHkqmQmT5YD2WR4BBwUdeQoFo8l/7tVs=
                github.com/envoyproxy/go-control-plane v0.10.3/go.mod h1:fJJn/j26vwOu972OllsvAgJJM//w9BV6Fxbg2LuVd34=
                github.com/envoyproxy/protoc-gen-validate v0.9.1/go.mod h1:OKNgG7TCp5pF4d6XftA0++PMirau2/yoOwVac3AbF2w=
                github.com/evanphx/json-patch v4.11.0+incompatible/go.mod h1:50XU6AFN0ol/bzJsmQLiYLvXMP4fmwYFNcr97nuDLSk=
                github.com/fatih/color v1.13.0/go.mod h1:kLAiJbzzSOZDVNGyDpeOxJ47H46qBXwg5ILebYFFOfk=
                github.com/felixge/httpsnoop v1.0.1/go.mod h1:m8KPJKqk1gH5J9DgRY2ASl2lWCfGKXixSwevea8zH2U=
                github.com/fogleman/gg v1.3.0/go.mod h1:R/bRT+9gY/C5z7JzPU0zXsXHKM4/ayA+zqcVNZzPa1k=
                github.com/form3tech-oss/jwt-go v3.2.3+incompatible/go.mod h1:pbq4aXjuKjdthFRnoDwaVPLA+WlJuPGy+QneDUgJi2k=
                github.com/frankban/quicktest v1.14.0/go.mod h1:NeW+ay9A/U67EYXNFA1nPE8e/tnQv/09mUdL/ijj8og=
                github.com/fsnotify/fsnotify v1.5.4/go.mod h1:OVB6XrOHzAwXMpEM7uPOzcehqUV2UqJxmVXmkdnm1bU=
                github.com/fullsailor/pkcs7 v0.0.0-20190404230743-d7302db945fa/go.mod h1:KnogPXtdwXqoenmZCw6S+25EAm2MkxbG0deNDu4cbSA=
                github.com/garyburd/redigo v0.0.0-20150301180006-535138d7bcd7/go.mod h1:NR3MbYisc3/PwhQ00EMzDiPmrwpPxAn5GI05/YaO1SY=
                github.com/getsentry/raven-go v0.2.0/go.mod h1:KungGk8q33+aIAZUIVWZDr2OfAEBsO49PX4NzFV5kcQ=
                github.com/ghodss/yaml v1.0.0/go.mod h1:4dBDuWmgqj2HViK6kFavaiC9ZROes6MMH2rRYeMEF04=
                github.com/go-fonts/dejavu v0.1.0/go.mod h1:4Wt4I4OU2Nq9asgDCteaAaWZOV24E+0/Pwo0gppep4g=
                github.com/go-fonts/latin-modern v0.2.0/go.mod h1:rQVLdDMK+mK1xscDwsqM5J8U2jrRa3T0ecnM9pNujks=
                github.com/go-fonts/liberation v0.2.0/go.mod h1:K6qoJYypsmfVjWg8KOVDQhLc8UDgIK2HYqyqAO9z7GY=
                github.com/go-fonts/stix v0.1.0/go.mod h1:w/c1f0ldAUlJmLBvlbkvVXLAD+tAMqobIIQpmnUIzUY=
                github.com/go-gl/glfw v0.0.0-20190409004039-e6da0acd62b1/go.mod h1:vR7hzQXu2zJy9AVAgeJqvqgH9Q5CA+iKCZ2gyEVpxRU=
                github.com/go-gl/glfw/v3.3/glfw v0.0.0-20200222043503-6f7a984d4dc4/go.mod h1:tQ2UAYgL5IevRw8kRxooKSPJfGvJ9fJQFa0TUsXzTg8=
                github.com/go-ini/ini v1.25.4/go.mod h1:ByCAeIL28uOIIG0E3PJtZPDL8WnHpFKFOtgjp+3Ies8=
                github.com/go-kit/kit v0.9.0/go.mod h1:xBxKIO96dXMWWy0MnWVtmwkA9/13aqxPnvrjFYMA2as=
                github.com/go-kit/log v0.1.0/go.mod h1:zbhenjAZHb184qTLMA9ZjW7ThYL0H2mk7Q6pNt4vbaY=
                github.com/go-latex/latex v0.0.0-20210823091927-c0d11ff05a81/go.mod h1:SX0U8uGpxhq9o2S/CELCSUxEWWAuoCUcVCQWv7G2OCk=
                github.com/go-logfmt/logfmt v0.5.0/go.mod h1:wCYkCAKZfumFQihp8CzCvQ3paCTfi41vtzG1KdI/P7A=
                github.com/go-logr/logr v1.2.2/go.mod h1:jdQByPbusPIv2/zmleS9BjJVeZ6kBagPoEUsqbVz/1A=
                github.com/go-logr/stdr v1.2.2/go.mod h1:mMo/vtBO5dYbehREoey6XUKy/eSumjCCveDpRre4VKE=
                github.com/go-openapi/jsonpointer v0.19.5/go.mod h1:Pl9vOtqEWErmShwVjC8pYs9cog34VGT37dQOVbmoatg=
                github.com/go-openapi/jsonreference v0.19.5/go.mod h1:RdybgQwPxbL4UEjuAruzK1x3nE69AqPYEJeo/TWfEeg=
                github.com/go-openapi/spec v0.19.3/go.mod h1:FpwSN1ksY1eteniUU7X0N/BgJ7a4WvBFVA8Lj9mJglo=
                github.com/go-openapi/swag v0.19.14/go.mod h1:QYRuS/SOXUCsnplDa677K7+DxSOj6IPNl/eQntq43wQ=
                github.com/go-pdf/fpdf v0.6.0/go.mod h1:HzcnA+A23uwogo0tp9yU+l3V+KXhiESpt1PMayhOh5M=
                github.com/go-redis/redis/v8 v8.11.5/go.mod h1:gREzHqY1hg6oD9ngVRbLStwAWKhA0FEgq8Jd4h5lpwo=
                github.com/go-sql-driver/mysql v1.6.0/go.mod h1:DCzpHaOWr8IXmIStZouvnhqoel9Qv2LBy8hT2VhHyBg=
                github.com/go-stack/stack v1.8.0/go.mod h1:v0f6uXyyMGvRgIKkXu+yp6POWl0qKG85gN/melR3HDY=
                github.com/go-task/slim-sprig v0.0.0-20210107165309-348f09dbbbc0/go.mod h1:fyg7847qk6SyHyPtNmDHnmrv/HOrqktSC+C9fM+CJOE=
                github.com/goccy/go-json v0.9.11/go.mod h1:6MelG93GURQebXPDq3khkgXZkazVtN9CRI+MGFi0w8I=
                github.com/godbus/dbus v0.0.0-20190422162347-ade71ed3457e/go.mod h1:bBOAhwG1umN6/6ZUMtDFBMQR8jRg9O75tm9K00oMsK4=
                github.com/godbus/dbus/v5 v5.0.6/go.mod h1:xhWf0FNVPg57R7Z0UbKHbJfkEywrmjJnf7w5xrFpKfA=
                github.com/gogo/googleapis v1.4.0/go.mod h1:5YRNX2z1oM5gXdAkurHa942MDgEJyk02w4OecKY87+c=
                github.com/gogo/protobuf v1.3.2/go.mod h1:P1XiOD3dCwIKUDQYPy72D8LYyHL2YPYrpS2s69NZV8Q=
                github.com/golang/freetype v0.0.0-20170609003504-e2365dfdc4a0/go.mod h1:E/TSTwGwJL78qG/PmXZO1EjYhfJinVAhrmmHX6Z8B9k=
                github.com/golang/glog v1.0.0/go.mod h1:EWib/APOK0SL3dFbYqvxE3UYd8E6s1ouQ7iEp/0LWV4=
                github.com/golang/groupcache v0.0.0-20210331224755-41bb18bfe9da/go.mod h1:cIg4eruTrX1D+g88fzRXU5OdNfaM+9IcxsU14FzY7Hc=
                github.com/golang/mock v1.6.0/go.mod h1:p6yTPP+5HYm5mzsMV8JkE6ZKdX+/wYM6Hr+LicevLPs=
                github.com/golang/protobuf v1.5.3/go.mod h1:XVQd3VNwM+JqD3oG2Ue2ip4fOMUkwXdXDdiuN0vRsmY=
                github.com/golang/snappy v0.0.4/go.mod h1:/XxbfmMg8lxefKM7IXC3fBNl/7bRcc72aCRzEWrmP2Q=
                github.com/google/btree v1.0.1/go.mod h1:xXMiIv4Fb/0kKde4SpL7qlzvu5cMJDRkFDxJfI9uaxA=
                github.com/google/flatbuffers v2.0.8+incompatible/go.mod h1:1AeVuKshWv4vARoZatz6mlQ0JxURH0Kv5+zNeJKJCa8=
                github.com/google/go-cmp v0.5.9/go.mod h1:17dUlkBOakJ0+DkrSSNjCkIjxS6bF9zb3elmeNGIjoY=
                github.com/google/go-containerregistry v0.5.1/go.mod h1:Ct15B4yir3PLOP5jsy0GNeYVaIZs/MK/Jz5any1wFW0=
                github.com/google/gofuzz v1.2.0/go.mod h1:dBl0BpW6vV/+mYPU4Po3pmUjxk6FQPldtuIdl/M65Eg=
                github.com/google/martian v2.1.0+incompatible/go.mod h1:9I4somxYTbIHy5NJKHRl3wXiIaQGbYVAs8BPL6v8lEs=
                github.com/google/martian/v3 v3.3.2/go.mod h1:oBOf6HBosgwRXnUGWUB05QECsc6uvmMiJ3+6W4l/CUk=
                github.com/google/pprof v0.0.0-20210720184732-4bb14d4b1be1/go.mod h1:kpwsk12EmLew5upagYY7GY0pfYCcupk39gWOCRROcvE=
                github.com/google/renameio v0.1.0/go.mod h1:KWCgfxg9yswjAJkECMjeO8J8rahYeXnNhOm40UhjYkI=
                github.com/google/shlex v0.0.0-20191202100458-e7afc7fbc510/go.mod h1:pupxD2MaaD3pAXIBCelhxNneeOaAeabZDe5s4K6zSpQ=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                github.com/googleapis/enterprise-certificate-proxy v0.2.3/go.mod h1:AwSRAtLfXpU5Nm3pW+v7rGDHp09LsPtGY9MduiEsR9k=
                github.com/googleapis/gax-go/v2 v2.7.1/go.mod h1:4orTrqY6hXxxaUL4LHIPl6lGo8vAE38/qKbhSAKP6QI=
                github.com/googleapis/gnostic v0.5.5/go.mod h1:7+EbHbldMins07ALC74bsA81Ovc97DwqyJO1AENw9kA=
                github.com/googleapis/go-type-adapters v1.0.0/go.mod h1:zHW75FOG2aur7gAO2B+MLby+cLsWGBF62rFAi7WjWO4=
                github.com/googleapis/google-cloud-go-testing v0.0.0-20200911160855-bcd43fbb19e8/go.mod h1:dvDLG8qkwmyD9a/MJJN3XJcT3xFxOKAvTZGvuZmac9g=
                github.com/gopherjs/gopherjs v0.0.0-20181017120253-0766667cb4d1/go.mod h1:wJfORRmW1u3UXTncJ5qlYoELFm8eSnnEO6hX4iZ3EWY=
                github.com/gorilla/handlers v0.0.0-20150720190736-60c7bfde3e33/go.mod h1:Qkdc/uu4tH4g6mTK6auzZ766c4CA0Ng8+o/OAirnOIQ=
                github.com/gorilla/mux v1.7.3/go.mod h1:1lud6UwP+6orDFRuTfBEV8e9/aOM/c4fVVCaMa2zaAs=
                github.com/gorilla/websocket v1.4.2/go.mod h1:YR8l580nyteQvAITg2hZ9XVh4b55+EU/adAjf1fMHhE=
                github.com/gregjones/httpcache v0.0.0-20180305231024-9cad4c3443a7/go.mod h1:FecbI9+v66THATjSRHfNgh1IVFe/9kFxbXtjV0ctIMA=
                github.com/grpc-ecosystem/go-grpc-middleware v1.3.0/go.mod h1:z0ButlSOZa5vEBq9m2m2hlwIgKw+rp3sdCBRoJY+30Y=
                github.com/grpc-ecosystem/go-grpc-prometheus v1.2.0/go.mod h1:8NvIoxWQoOIhqOTXgfV/d3M/q6VIi02HzZEHgUlZvzk=
                github.com/grpc-ecosystem/grpc-gateway v1.16.0/go.mod h1:BDjrQk3hbvj6Nolgz8mAMFbcEtjT1g+wF4CSlocrBnw=
                github.com/grpc-ecosystem/grpc-gateway/v2 v2.11.3/go.mod h1:o//XUCC/F+yRGJoPO/VU0GSB0f8Nhgmxx0VIRUvaC0w=
                github.com/hashicorp/consul/api v1.1.0/go.mod h1:VmuI/Lkw1nC05EYQWNKwWGbkg+FbDBtguAZLlVdkD9Q=
                github.com/hashicorp/consul/sdk v0.1.1/go.mod h1:VKf9jXwCTEY1QZP2MOLRhb5i/I/ssyNV1vwHyQBF0x8=
                github.com/hashicorp/errwrap v1.1.0/go.mod h1:YH+1FKiLXxHSkmPseP+kNlulaMuP3n2brvKWEqk/Jc4=
                github.com/hashicorp/go-cleanhttp v0.5.1/go.mod h1:JpRdi6/HCYpAwUzNwuwqhbovhLtngrth3wmdIIUrZ80=
                github.com/hashicorp/go-immutable-radix v1.0.0/go.mod h1:0y9vanUI8NX6FsYoO3zeMjhV/C5i9g4Q3DwcSNZ4P60=
                github.com/hashicorp/go-msgpack v0.5.3/go.mod h1:ahLV/dePpqEmjfWmKiqvPkv/twdG7iPBM1vqhUKIvfM=
                github.com/hashicorp/go-multierror v1.1.1/go.mod h1:iw975J/qwKPdAO1clOe2L8331t/9/fmwbPZ6JB6eMoM=
                github.com/hashicorp/go-rootcerts v1.0.0/go.mod h1:K6zTfqpRlCUIjkwsN4Z+hiSfzSTQa6eBIzfwKfwNnHU=
                github.com/hashicorp/go-sockaddr v1.0.0/go.mod h1:7Xibr9yA9JjQq1JpNB2Vw7kxv8xerXegt+ozgdvDeDU=
                github.com/hashicorp/go-syslog v1.0.0/go.mod h1:qPfqrKkXGihmCqbJM2mZgkZGvKG1dFdvsLplgctolz4=
                github.com/hashicorp/go-uuid v1.0.1/go.mod h1:6SBZvOh/SIDV7/2o3Jml5SYk/TvGqwFJ/bN7x4byOro=
                github.com/hashicorp/go.net v0.0.1/go.mod h1:hjKkEWcCURg++eb33jQU7oqQcI9XDCnUzHA0oac0k90=
                github.com/hashicorp/golang-lru v0.5.1/go.mod h1:/m3WP610KZHVQ1SGc6re/UDhFvYD7pJ4Ao+sR/qLZy8=
                github.com/hashicorp/hcl v1.0.0/go.mod h1:E5yfLk+7swimpb2L/Alb/PJmXilQ/rhwaUYs4T20WEQ=
                github.com/hashicorp/logutils v1.0.0/go.mod h1:QIAnNjmIWmVIIkWDTG1z5v++HQmx9WQRO+LraFDTW64=
                github.com/hashicorp/mdns v1.0.0/go.mod h1:tL+uN++7HEJ6SQLQ2/p+z2pH24WQKWjBPkE0mNTz8vQ=
                github.com/hashicorp/memberlist v0.1.3/go.mod h1:ajVTdAv/9Im8oMAAj5G31PhhMCZJV2pPBoIllUwCN7I=
                github.com/hashicorp/serf v0.8.2/go.mod h1:6hOLApaqBFA1NXqRQAsxw9QxuDEvNxSQRwA/JwenrHc=
                github.com/heetch/avro v0.4.4/go.mod h1:c0whqijPh/C+RwnXzAHFit01tdtf7gMeEHYSbICxJjU=
                github.com/hpcloud/tail v1.0.0/go.mod h1:ab1qPbhIpdTxEkNHXyeSf5vhxWSCs/tWer42PpOxQnU=
                github.com/iancoleman/orderedmap v0.0.0-20190318233801-ac98e3ecb4b0/go.mod h1:N0Wam8K1arqPXNWjMo21EXnBPOPp36vB07FNRdD2geA=
                github.com/iancoleman/strcase v0.2.0/go.mod h1:iwCmte+B7n89clKwxIoIXy/HfoL7AsD47ZCWhYzw7ho=
                github.com/ianlancetaylor/demangle v0.0.0-20200824232613-28f6c0f3b639/go.mod h1:aSSvb/t6k1mPoxDqO4vJh6VOCGPwU4O0C2/Eqndh1Sc=
                github.com/imdario/mergo v0.3.12/go.mod h1:jmQim1M+e3UYxmgPu/WyfjB3N3VflVyUjjjwH0dnCYA=
                github.com/inconshreveable/mousetrap v1.0.0/go.mod h1:PxqpIevigyE2G7u3NXJIT2ANytuPF1OarO4DADm73n8=
                github.com/intel/goresctrl v0.2.0/go.mod h1:+CZdzouYFn5EsxgqAQTEzMfwKwuc0fVdMrT9FCCAVRQ=
                github.com/invopop/jsonschema v0.7.0/go.mod h1:O9uiLokuu0+MGFlyiaqtWxwqJm41/+8Nj0lD7A36YH0=
                github.com/j-keck/arping v1.0.2/go.mod h1:aJbELhR92bSk7tp79AWM/ftfc90EfEi2bQJrbBFOsPw=
                github.com/jhump/gopoet v0.1.0/go.mod h1:me9yfT6IJSlOL3FCfrg+L6yzUEZ+5jW6WHt4Sk+UPUI=
                github.com/jhump/goprotoc v0.5.0/go.mod h1:VrbvcYrQOrTi3i0Vf+m+oqQWk9l72mjkJCYo7UvLHRQ=
                github.com/jhump/protoreflect v1.14.1/go.mod h1:JytZfP5d0r8pVNLZvai7U/MCuTWITgrI4tTg7puQFKI=
                github.com/jmespath/go-jmespath v0.0.0-20160803190731-bd40a432e4c7/go.mod h1:Nht3zPeWKUH0NzdCt2Blrr5ys8VGpn0CEB0cQHVjt7k=
                github.com/joefitzgerald/rainbow-reporter v0.1.0/go.mod h1:481CNgqmVHQZzdIbN52CupLJyoVwB10FQ/IQlF1pdL8=
                github.com/jonboulle/clockwork v0.2.2/go.mod h1:Pkfl5aHPm1nk2H9h0bjmnJD/BcgbGXUBGnn1kMkgxc8=
                github.com/josharian/intern v1.0.0/go.mod h1:5DoeVV0s6jJacbCEi61lwdGj/aVlrQvzHFFd8Hwg//Y=
                github.com/jpillora/backoff v1.0.0/go.mod h1:J/6gKK9jxlEcS3zixgDgUAsiuZ7yrSoa/FX5e0EB2j4=
                github.com/json-iterator/go v1.1.12/go.mod h1:e30LSqwooZae/UwlEbR2852Gd8hjQvJoHmT4TnhNGBo=
                github.com/jstemmer/go-junit-report v0.9.1/go.mod h1:Brl9GWCQeLvo8nXZwPNNblvFj/XSXhF0NWZEnDohbsk=
                github.com/jtolds/gls v4.20.0+incompatible/go.mod h1:QJZ7F/aHp+rZTRtaJ1ow/lLfFfVYBRgL+9YlvaHOwJU=
                github.com/juju/qthttptest v0.1.1/go.mod h1:aTlAv8TYaflIiTDIQYzxnl1QdPjAg8Q8qJMErpKy6A4=
                github.com/julienschmidt/httprouter v1.3.0/go.mod h1:JR6WtHb+2LUe8TCKY3cZOxFyyO8IZAc4RVcycCCAKdM=
                github.com/jung-kurt/gofpdf v1.0.3-0.20190309125859-24315acbbda5/go.mod h1:7Id9E/uU8ce6rXgefFLlgrJj/GYY22cpxn+r32jIOes=
                github.com/kballard/go-shellquote v0.0.0-20180428030007-95032a82bc51/go.mod h1:CzGEWj7cYgsdH8dAjBGEr58BoE7ScuLd+fwFZ44+/x8=
                github.com/kisielk/errcheck v1.5.0/go.mod h1:pFxgyoBC7bSaBwPgfKdkLd5X25qrDl4LWUI2bnpBCr8=
                github.com/kisielk/gotool v1.0.0/go.mod h1:XhKaO+MFFWcvkIS/tQcRk01m1F5IRFswLeQ+oQHNcck=
                github.com/klauspost/asmfmt v1.3.2/go.mod h1:AG8TuvYojzulgDAMCnYn50l/5QV3Bs/tp6j0HLHbNSE=
                github.com/klauspost/compress v1.15.9/go.mod h1:PhcZ0MbTNciWF3rruxRgKxI5NkcHHrHUDtV4Yw2GlzU=
                github.com/klauspost/cpuid/v2 v2.0.9/go.mod h1:FInQzS24/EEf25PyTYn52gqo7WaD8xa0213Md/qVLRg=
                github.com/konsorten/go-windows-terminal-sequences v1.0.3/go.mod h1:T0+1ngSBFLxvqU3pZ+m/2kptfBszLMUkC4ZK/EgS/cQ=
                github.com/kr/fs v0.1.0/go.mod h1:FFnZGqtBN9Gxj7eW1uZ42v5BccTP0vu6NEaFoC2HwRg=
                github.com/kr/logfmt v0.0.0-20140226030751-b84e30acd515/go.mod h1:+0opPa2QZZtGFBFZlji/RkVcI2GknAs/DXo4wKdlNEc=
                github.com/kr/pretty v0.3.0/go.mod h1:640gp4NfQd8pI5XOwp5fnNeVWj67G7CFk/SaSQn7NBk=
                github.com/kr/pty v1.1.5/go.mod h1:9r2w37qlBe7rQ6e1fg1S/9xpWHSnaqNdHD3WcMdbPDA=
                github.com/kr/text v0.2.0/go.mod h1:eLer722TekiGuMkidMxC/pM04lWEeraHUUmBw8l2grE=
                github.com/linkedin/goavro/v2 v2.11.1/go.mod h1:UgQUb2N/pmueQYH9bfqFioWxzYCZXSfF8Jw03O5sjqA=
                github.com/linuxkit/virtsock v0.0.0-20201010232012-f8cee7dfc7a3/go.mod h1:3r6x7q95whyfWQpmGZTu3gk3v2YkMi05HEzl7Tf7YEo=
                github.com/lyft/protoc-gen-star v0.6.1/go.mod h1:TGAoBVkt8w7MPG72TrKIu85MIdXwDuzJYeZuUPFPNwA=
                github.com/magiconair/properties v1.8.6/go.mod h1:y3VJvCyxH9uVvJTWEGAELF3aiYNyPKd5NZ3oSwXrF60=
                github.com/mailru/easyjson v0.7.6/go.mod h1:xzfreul335JAWq5oZzymOObrkdz5UnU4kGfJJLY9Nlc=
                github.com/marstr/guid v1.1.0/go.mod h1:74gB1z2wpxxInTG6yaqA7KrtM0NZ+RbrcqDvYHefzho=
                github.com/mattn/go-colorable v0.1.12/go.mod h1:u5H1YNBxpqRaxsYJYSkiCWKzEfiAb1Gb520KVy5xxl4=
                github.com/mattn/go-isatty v0.0.16/go.mod h1:kYGgaQfpe5nmfYZH+SKPsOc2e4SrIfOl2e/yFXSvRLM=
                github.com/mattn/go-runewidth v0.0.2/go.mod h1:LwmH8dsx7+W8Uxz3IHJYH5QSwggIsqBzpuz5H//U1FU=
                github.com/mattn/go-shellwords v1.0.12/go.mod h1:EZzvwXDESEeg03EKmM+RmDnNOPKG4lLtQsUlTZDWQ8Y=
                github.com/mattn/go-sqlite3 v1.14.14/go.mod h1:NyWgC/yNuGj7Q9rpYnZvas74GogHl5/Z4A/KQRfk6bU=
                github.com/matttproud/golang_protobuf_extensions v1.0.2-0.20181231171920-c182affec369/go.mod h1:BSXmuO+STAnVfrANrmjBb36TMTDstsz7MSK+HVaYKv4=
                github.com/maxbrunsfeld/counterfeiter/v6 v6.2.2/go.mod h1:eD9eIE7cdwcMi9rYluz88Jz2VyhSmden33/aXg4oVIY=
                github.com/miekg/dns v1.0.14/go.mod h1:W1PPwlIAgtquWBMBEV9nkV9Cazfe8ScdGz/Lj7v3Nrg=
                github.com/miekg/pkcs11 v1.1.1/go.mod h1:XsNlhZGX73bx86s2hdc/FuaLm2CPZJemRLMA+WTFxgs=
                github.com/minio/asm2plan9s v0.0.0-20200509001527-cdd76441f9d8/go.mod h1:mC1jAcsrzbxHt8iiaC+zU4b1ylILSosueou12R++wfY=
                github.com/minio/c2goasm v0.0.0-20190812172519-36a3d3bbc4f3/go.mod h1:RagcQ7I8IeTMnF8JTXieKnO4Z6JCsikNEzj0DwauVzE=
                github.com/mistifyio/go-zfs v2.1.2-0.20190413222219-f784269be439+incompatible/go.mod h1:8AuVvqP/mXw1px98n46wfvcGfQ4ci2FwoAjKYxuo3Z4=
                github.com/mitchellh/cli v1.0.0/go.mod h1:hNIlj7HEI86fIcpObd7a0FcrxTWetlwJDGcceTlRvqc=
                github.com/mitchellh/go-homedir v1.1.0/go.mod h1:SfyaCUpYCn1Vlf4IUYiD9fPX4A5wJrkLzIz1N1q0pr0=
                github.com/mitchellh/go-testing-interface v1.0.0/go.mod h1:kRemZodwjscx+RGhAo8eIhFbs2+BFgRtFPeD/KE+zxI=
                github.com/mitchellh/gox v0.4.0/go.mod h1:Sd9lOJ0+aimLBi73mGofS1ycjY8lL3uZM3JPS42BGNg=
                github.com/mitchellh/iochan v1.0.0/go.mod h1:JwYml1nuB7xOzsp52dPpHFffvOCDupsG0QubkSMEySY=
                github.com/mitchellh/mapstructure v1.1.2/go.mod h1:FVVH3fgwuzCH5S8UJGiWEs2h04kUh9fWfEaFds41c1Y=
                github.com/mitchellh/osext v0.0.0-20151018003038-5e2d6d41470f/go.mod h1:OkQIRizQZAeMln+1tSwduZz7+Af5oFlKirV/MSYes2A=
                github.com/moby/locker v1.0.1/go.mod h1:S7SDdo5zpBK84bzzVlKr2V0hz+7x9hWbYC/kq7oQppc=
                github.com/moby/spdystream v0.2.0/go.mod h1:f7i0iNDQJ059oMTcWxx8MA/zKFIuD/lY+0GqbN2Wy8c=
                github.com/moby/sys/mount v0.3.3/go.mod h1:PBaEorSNTLG5t/+4EgukEQVlAvVEc6ZjTySwKdqp5K0=
                github.com/moby/sys/mountinfo v0.6.2/go.mod h1:IJb6JQeOklcdMU9F5xQ8ZALD+CUr5VlGpwtX+VE0rpI=
                github.com/moby/sys/signal v0.6.0/go.mod h1:GQ6ObYZfqacOwTtlXvcmh9A26dVRul/hbOZn88Kg8Tg=
                github.com/moby/sys/symlink v0.2.0/go.mod h1:7uZVF2dqJjG/NsClqul95CqKOBRQyYSNnJ6BMgR/gFs=
                github.com/moby/term v0.0.0-20210619224110-3f7ff695adc6/go.mod h1:E2VnQOmVuvZB6UYnnDB0qG5Nq/1tD9acaOpo6xmt0Kw=
                github.com/modern-go/concurrent v0.0.0-20180306012644-bacd9c7ef1dd/go.mod h1:6dJC0mAP4ikYIbvyc7fijjWJddQyLn8Ig3JB5CqoB9Q=
                github.com/modern-go/reflect2 v1.0.2/go.mod h1:yWuevngMOJpCy52FWWMvUC8ws7m/LJsjYzDa0/r8luk=
                github.com/morikuni/aec v1.0.0/go.mod h1:BbKIizmSmc5MMPqRYbxO4ZU0S0+P200+tUnFx7PXmsc=
                github.com/mrunalp/fileutils v0.5.0/go.mod h1:M1WthSahJixYnrXQl/DFQuteStB1weuxD2QJNHXfbSQ=
                github.com/munnerz/goautoneg v0.0.0-20191010083416-a7dc8b61c822/go.mod h1:+n7T8mK8HuQTcFwEeznm/DIxMOiR9yIdICNftLE1DvQ=
                github.com/mwitkow/go-conntrack v0.0.0-20190716064945-2f068394615f/go.mod h1:qRWi+5nqEBWmkhHvq77mSJWrCKwh8bxhgT7d/eI7P4U=
                github.com/mxk/go-flowrate v0.0.0-20140419014527-cca7078d478f/go.mod h1:ZdcZmHo+o7JKHSa8/e818NopupXU1YMK5fe1lsApnBw=
                github.com/ncw/swift v1.0.47/go.mod h1:23YIA4yWVnGwv2dQlN4bB7egfYX6YLn0Yo/S6zZO/ZM=
                github.com/networkplumbing/go-nft v0.2.0/go.mod h1:HnnM+tYvlGAsMU7yoYwXEVLLiDW9gdMmb5HoGcwpuQs=
                github.com/niemeyer/pretty v0.0.0-20200227124842-a10e7caefd8e/go.mod h1:zD1mROLANZcx1PVRCS0qkT7pwLkGfwJo4zjcN/Tysno=
                github.com/nxadm/tail v1.4.8/go.mod h1:+ncqLTQzXmGhMZNUePPaPqPvBxHAIsmXswZKocGu+AU=
                github.com/oklog/ulid v1.3.1/go.mod h1:CirwcVhetQ6Lv90oh/F+FBtV6XMibvdAFo93nm5qn4U=
                github.com/olekukonko/tablewriter v0.0.0-20170122224234-a0225b3f23b5/go.mod h1:vsDQFd/mU46D+Z4whnwzcISnGGzXWMclvtLoiIKAKIo=
                github.com/onsi/ginkgo v1.16.5/go.mod h1:+E8gABHa3K6zRBolWtd+ROzc/U5bkGt0FwiG042wbpU=
                github.com/onsi/ginkgo/v2 v2.1.3/go.mod h1:vw5CSIxN1JObi/U8gcbwft7ZxR2dgaR70JSE3/PpL4c=
                github.com/onsi/gomega v1.18.1/go.mod h1:0q+aL8jAiMXy9hbwj2mr5GziHiwhAIQpFmmtT5hitRs=
                github.com/opencontainers/go-digest v1.0.0/go.mod h1:0JzlMkj0TRzQZfJkVvzbP0HBR3IKzErnv2BNG4W4MAM=
                github.com/opencontainers/image-spec v1.0.3-0.20211202183452-c5a74bcca799/go.mod h1:BtxoFyWECRxE4U/7sNtV5W15zMzWCbyJoFRP3s7yZA0=
                github.com/opencontainers/runc v1.1.3/go.mod h1:1J5XiS+vdZ3wCyZybsuxXZWGrgSr8fFJHLXuG2PsnNg=
                github.com/opencontainers/runtime-spec v1.0.3-0.20210326190908-1c3f411f0417/go.mod h1:jwyrGlmzljRJv/Fgzds9SsS/C5hL+LL3ko9hs6T5lQ0=
                github.com/opencontainers/runtime-tools v0.0.0-20181011054405-1d69bd0f9c39/go.mod h1:r3f7wjNzSs2extwzU3Y+6pKfobzPh+kKFJ3ofN+3nfs=
                github.com/opencontainers/selinux v1.10.1/go.mod h1:2i0OySw99QjzBBQByd1Gr9gSjvuho1lHsJxIJ3gGbJI=
                github.com/opentracing/opentracing-go v1.1.0/go.mod h1:UkNAQd3GIcIGf0SeVgPpRdFStlNbqXla1AfSYxPUl2o=
                github.com/pascaldekloe/goe v0.0.0-20180627143212-57f6aae5913c/go.mod h1:lzWF7FIEvWOWxwDKqyGYQf6ZUaNfKdP144TG7ZOy1lc=
                github.com/pelletier/go-toml v1.9.3/go.mod h1:u1nR/EPcESfeI/szUZKdtJ0xRNbUoANCkoOuaOx1Y+c=
                github.com/peterbourgon/diskv v2.0.1+incompatible/go.mod h1:uqqh8zWWbv1HBMNONnaR/tNboyR3/BZd58JJSHlUSCU=
                github.com/phpdave11/gofpdf v1.4.2/go.mod h1:zpO6xFn9yxo3YLyMvW8HcKWVdbNqgIfOOp2dXMnm1mY=
                github.com/phpdave11/gofpdi v1.0.13/go.mod h1:vBmVV0Do6hSBHC8uKUQ71JGW+ZGQq74llk/7bXwjDoI=
                github.com/pierrec/lz4/v4 v4.1.15/go.mod h1:gZWDp/Ze/IJXGXf23ltt2EXimqmTUXEy0GFuRQyBid4=
                github.com/pkg/diff v0.0.0-20210226163009-20ebb0f2a09e/go.mod h1:pJLUxLENpZxwdsKMEsNbx1VGcRFpLqf3715MtcvvzbA=
                github.com/pkg/errors v0.9.1/go.mod h1:bwawxfHBFNV+L2hUp1rHADufV3IMtnDRdf1r5NINEl0=
                github.com/pkg/sftp v1.13.1/go.mod h1:3HaPG6Dq1ILlpPZRO0HVMrsydcdLt6HRDccSgb87qRg=
                github.com/pmezard/go-difflib v1.0.0/go.mod h1:iKH77koFhYxTK1pcRnkKkqfTogsbg7gZNVY4sRDYZ/4=
                github.com/posener/complete v1.1.1/go.mod h1:em0nMJCgc9GFtwrmVmEMR/ZL6WyhyjMBndrE9hABlRI=
                github.com/pquerna/cachecontrol v0.0.0-20171018203845-0dec1b30a021/go.mod h1:prYjPmNq4d1NPVmpShWobRqXY3q7Vp+80DqgxxUrUIA=
                github.com/prometheus/client_golang v1.11.1/go.mod h1:Z6t4BnS23TR94PD6BsDNk8yVqroYurpAkEiz0P2BEV0=
                github.com/prometheus/client_model v0.2.0/go.mod h1:xMI15A0UPsDsEKsMN9yxemIoYk6Tm2C1GtYGdfGttqA=
                github.com/prometheus/common v0.30.0/go.mod h1:vu+V0TpY+O6vW9J44gczi3Ap/oXXR10b+M/gUGO4Hls=
                github.com/prometheus/procfs v0.7.3/go.mod h1:cz+aTbrPOrUb4q7XlbU9ygM+/jj0fzG6c1xBZuNvfVA=
                github.com/prometheus/tsdb v0.7.1/go.mod h1:qhTCs0VvXwvX/y3TZrWD7rabWM+ijKTux40TwIPHuXU=
                github.com/remyoudompheng/bigfft v0.0.0-20200410134404-eec4a21b6bb0/go.mod h1:qqbHyh8v60DhA7CoWK5oRCqLrMHRGoxYCSS9EjAz6Eo=
                github.com/rogpeppe/clock v0.0.0-20190514195947-2896927a307a/go.mod h1:4r5QyqhjIWCcK8DO4KMclc5Iknq5qVBAlbYYzAbUScQ=
                github.com/rogpeppe/fastuuid v1.2.0/go.mod h1:jVj6XXZzXRy/MSR5jhDC/2q6DgLz+nrA6LYCDYWNEvQ=
                github.com/rogpeppe/go-internal v1.9.0/go.mod h1:WtVeX8xhTBvf0smdhujwtBcq4Qrzq/fJaraNFVN+nFs=
                github.com/russross/blackfriday/v2 v2.0.1/go.mod h1:+Rmxgy9KzJVeS9/2gXHxylqXiyQDYRxCVz55jmeOWTM=
                github.com/ruudk/golang-pdf417 v0.0.0-20201230142125-a7e3863a1245/go.mod h1:pQAZKsJ8yyVxGRWYNEm9oFB8ieLgKFnamEyDmSA0BRk=
                github.com/ryanuber/columnize v0.0.0-20160712163229-9b3edd62028f/go.mod h1:sm1tb6uqfes/u+d4ooFouqFdy9/2g9QGwK3SQygK0Ts=
                github.com/safchain/ethtool v0.0.0-20210803160452-9aa261dae9b1/go.mod h1:Z0q5wiBQGYcxhMZ6gUqHn6pYNLypFAvaL3UvgZLR0U4=
                github.com/santhosh-tekuri/jsonschema/v5 v5.2.0/go.mod h1:FKdcjfQW6rpZSnxxUvEA5H/cDPdvJ/SZJQLWWXWGrZ0=
                github.com/satori/go.uuid v1.2.0/go.mod h1:dA0hQrYB0VpLJoorglMZABFdXlWrHn1NEOzdhQKdks0=
                github.com/sclevine/agouti v3.0.0+incompatible/go.mod h1:b4WX9W9L1sfQKXeJf1mUTLZKJ48R1S7H23Ji7oFO5Bw=
                github.com/sclevine/spec v1.2.0/go.mod h1:W4J29eT/Kzv7/b9IWLB055Z+qvVC9vt0Arko24q7p+U=
                github.com/sean-/seed v0.0.0-20170313163322-e2103e2c3529/go.mod h1:DxrIzT+xaE7yg65j358z/aeFdxmN0P9QXhEzd20vsDc=
                github.com/seccomp/libseccomp-golang v0.9.2-0.20220502022130-f33da4d89646/go.mod h1:JA8cRccbGaA1s33RQf7Y1+q9gHmZX1yB/z9WDN1C6fg=
                github.com/shurcooL/sanitized_anchor_name v1.0.0/go.mod h1:1NzhyTcUVG4SuEtjjoZeVRXNmyL/1OwPU0+IJeTBvfc=
                github.com/sirupsen/logrus v1.8.1/go.mod h1:yWOB1SBYBC5VeMP7gHvWumXLIWorT60ONWic61uBYv0=
                github.com/smartystreets/assertions v0.0.0-20180927180507-b2de0cb4f26d/go.mod h1:OnSkiWE9lh6wB0YB77sQom3nweQdgAjqCqsofrRNTgc=
                github.com/smartystreets/goconvey v1.6.4/go.mod h1:syvi0/a8iFYH4r/RixwvyeAJjdLS9QV7WQ/tjFTllLA=
                github.com/soheilhy/cmux v0.1.5/go.mod h1:T7TcVDs9LWfQgPlPsdngu6I6QIoyIFZDDC6sNE1GqG0=
                github.com/spaolacci/murmur3 v0.0.0-20180118202830-f09979ecbc72/go.mod h1:JwIasOWyU6f++ZhiEuf87xNszmSA2myDM2Kzu9HwQUA=
                github.com/spf13/afero v1.9.2/go.mod h1:iUV7ddyEEZPO5gA3zD4fJt6iStLlL+Lg4m2cihcDf8Y=
                github.com/spf13/cast v1.3.0/go.mod h1:Qx5cxh0v+4UWYiBimWS+eyWzqEqokIECu5etghLkUJE=
                github.com/spf13/cobra v1.1.3/go.mod h1:pGADOWyqRD/YMrPZigI/zbliZ2wVD/23d+is3pSWzOo=
                github.com/spf13/jwalterweatherman v1.0.0/go.mod h1:cQK4TGJAtQXfYWX+Ddv3mKDzgVb68N+wFjFa4jdeBTo=
                github.com/spf13/pflag v1.0.5/go.mod h1:McXfInJRrz4CZXVZOBLb0bTZqETkiAhM9Iw0y3An2Bg=
                github.com/spf13/viper v1.7.0/go.mod h1:8WkrPz2fc9jxqZNCJI/76HCieCp4Q8HaLFoCha5qpdg=
                github.com/stefanberger/go-pkcs11uri v0.0.0-20201008174630-78d3cae3a980/go.mod h1:AO3tvPzVZ/ayst6UlUKUv6rcPQInYe3IknH3jYhAKu8=
                github.com/stoewer/go-strcase v1.2.0/go.mod h1:IBiWB2sKIp3wVVQ3Y035++gc+knqhUQag1KpM8ahLw8=
                github.com/stretchr/objx v0.5.0/go.mod h1:Yh+to48EsGEfYuaHDzXPcE3xhTkx73EhmCGUpEOglKo=
                github.com/stretchr/testify v1.8.2/go.mod h1:w2LPCIKwWwSfY2zedu0+kehJoqGctiVI29o6fzry7u4=
                github.com/subosito/gotenv v1.2.0/go.mod h1:N0PQaV/YGNqwC0u51sEeR/aUtSLEXKX9iv69rRypqCw=
                github.com/syndtr/gocapability v0.0.0-20200815063812-42c35b437635/go.mod h1:hkRG7XYTFWNJGYcbNJQlaLq0fg1yr4J4t/NcTQtrfww=
                github.com/tchap/go-patricia v2.2.6+incompatible/go.mod h1:bmLyhP68RS6kStMGxByiQ23RP/odRBOTVjwp2cDyi6I=
                github.com/testcontainers/testcontainers-go v0.14.0/go.mod h1:hSRGJ1G8Q5Bw2gXgPulJOLlEBaYJHeBSOkQM5JLG+JQ=
                github.com/tmc/grpc-websocket-proxy v0.0.0-20201229170055-e5319fda7802/go.mod h1:ncp9v5uamzpCO7NfCPTXjqaC+bZgJeR0sMTm6dMHP7U=
                github.com/tv42/httpunix v0.0.0-20191220191345-2ba4b9c3382c/go.mod h1:hzIxponao9Kjc7aWznkXaL4U4TWaDSs8zcsY4Ka08nM=
                github.com/ugorji/go v1.1.4/go.mod h1:uQMGLiO92mf5W77hV/PUCpI3pbzQx3CRekS0kk+RGrc=
                github.com/urfave/cli v1.22.2/go.mod h1:Gos4lmkARVdJ6EkW0WaNv/tZAAMe9V7XWyB60NtXRu0=
                github.com/vishvananda/netlink v1.1.1-0.20210330154013-f5de75959ad5/go.mod h1:twkDnbuQxJYemMlGd4JFIcuhgX83tXhKS2B/PRMpOho=
                github.com/vishvananda/netns v0.0.0-20210104183010-2eb08e3e575f/go.mod h1:DD4vA1DwXk04H54A1oHXtwZmA0grkVMdPxx/VGLCah0=
                github.com/willf/bitset v1.1.11/go.mod h1:83CECat5yLh5zVOf4P1ErAgKA5UDvKtgyUABdr3+MjI=
                github.com/xeipuuv/gojsonpointer v0.0.0-20180127040702-4e3ac2762d5f/go.mod h1:N2zxlSyiKSe5eX1tZViRH5QA0qijqEDrYZiPEAiq3wU=
                github.com/xeipuuv/gojsonreference v0.0.0-20180127040603-bd5ef7bd5415/go.mod h1:GwrjFmJcFw6At/Gs6z4yjiIwzuJ1/+UwLxMQDVQXShQ=
                github.com/xeipuuv/gojsonschema v0.0.0-20180618132009-1d523034197f/go.mod h1:5yf86TLmAcydyeJq5YvxkGPE2fm/u4myDekKRoLuqhs=
                github.com/xiang90/probing v0.0.0-20190116061207-43a291ad63a2/go.mod h1:UETIi67q53MR2AWcXfiuqkDkRtnGDLqkBTpCHuJHxtU=
                github.com/xordataexchange/crypt v0.0.3-0.20170626215501-b2862e3d0a77/go.mod h1:aYKd//L2LvnjZzWKhF00oedf4jCCReLcmhLdhm1A27Q=
                github.com/yuin/goldmark v1.4.13/go.mod h1:6yULJ656Px+3vBD8DxQVa3kxgyrAnzto9xy5taEt/CY=
                github.com/yvasiyarov/go-metrics v0.0.0-20140926110328-57bccd1ccd43/go.mod h1:aX5oPXxHm3bOH+xeAttToC8pqch2ScQN/JoXYupl6xs=
                github.com/yvasiyarov/gorelic v0.0.0-20141212073537-a9bba5b9ab50/go.mod h1:NUSPSUX/bi6SeDMUh6brw0nXpxHnc96TguQh0+r/ssA=
                github.com/yvasiyarov/newrelic_platform_go v0.0.0-20140908184405-b21fdbd4370f/go.mod h1:GlGEuHIJweS1mbCqG+7vt2nvWLzLLnRHbXz5JKd/Qbg=
                github.com/zeebo/assert v1.3.0/go.mod h1:Pq9JiuJQpG8JLJdtkwrJESF0Foym2/D9XMU5ciN/wJ0=
                github.com/zeebo/xxh3 v1.0.2/go.mod h1:5NWz9Sef7zIDm2JHfFlcQvNekmcEl9ekUZQQKCYaDcA=
                go.etcd.io/bbolt v1.3.6/go.mod h1:qXsaaIqmgQH0T+OPdb99Bf+PKfBBQVAdyD6TY9G8XM4=
                go.etcd.io/etcd v0.5.0-alpha.5.0.20200910180754-dd1b699fc489/go.mod h1:yVHk9ub3CSBatqGNg7GRmsnfLWtoW60w4eDYfh7vHDg=
                go.etcd.io/etcd/api/v3 v3.5.0/go.mod h1:cbVKeC6lCfl7j/8jBhAK6aIYO9XOjdptoxU/nLQcPvs=
                go.etcd.io/etcd/client/pkg/v3 v3.5.0/go.mod h1:IJHfcCEKxYu1Os13ZdwCwIUTUVGYTSAM3YSwc9/Ac1g=
                go.etcd.io/etcd/client/v2 v2.305.0/go.mod h1:h9puh54ZTgAKtEbut2oe9P4L/oqKCVB6xsXlzd7alYQ=
                go.etcd.io/etcd/client/v3 v3.5.0/go.mod h1:AIKXXVX/DQXtfTEqBryiLTUXwON+GuvO6Z7lLS/oTh0=
                go.etcd.io/etcd/pkg/v3 v3.5.0/go.mod h1:UzJGatBQ1lXChBkQF0AuAtkRQMYnHubxAEYIrC3MSsE=
                go.etcd.io/etcd/raft/v3 v3.5.0/go.mod h1:UFOHSIvO/nKwd4lhkwabrTD3cqW5yVyYYf/KlD00Szc=
                go.etcd.io/etcd/server/v3 v3.5.0/go.mod h1:3Ah5ruV+M+7RZr0+Y/5mNLwC+eQlni+mQmOVdCRJoS4=
                go.mozilla.org/pkcs7 v0.0.0-20200128120323-432b2356ecb1/go.mod h1:SNgMg+EgDFwmvSmLRTNKC5fegJjB7v23qTQ0XLGUNHk=
                go.opencensus.io v0.24.0/go.mod h1:vNK8G9p7aAivkbmorf4v+7Hgx+Zs0yY+0fOtgBfjQKo=
                go.opentelemetry.io/contrib v0.20.0/go.mod h1:G/EtFaa6qaN7+LxqfIAT3GiZa7Wv5DTBUzl5H4LY0Kc=
                go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc v0.28.0/go.mod h1:vEhqr0m4eTc+DWxfsXoXue2GBgV2uUwVznkGIHW/e5w=
                go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp v0.20.0/go.mod h1:2AboqHi0CiIZU0qwhtUfCYD1GeUzvvIXWNkhDt7ZMG4=
                go.opentelemetry.io/otel v1.3.0/go.mod h1:PWIKzi6JCp7sM0k9yZ43VX+T345uNbAkDKwHVjb2PTs=
                go.opentelemetry.io/otel/exporters/otlp v0.20.0/go.mod h1:YIieizyaN77rtLJra0buKiNBOm9XQfkPEKBeuhoMwAM=
                go.opentelemetry.io/otel/exporters/otlp/internal/retry v1.3.0/go.mod h1:VpP4/RMn8bv8gNo9uK7/IMY4mtWLELsS+JIP0inH0h4=
                go.opentelemetry.io/otel/exporters/otlp/otlptrace v1.3.0/go.mod h1:hO1KLR7jcKaDDKDkvI9dP/FIhpmna5lkqPUQdEjFAM8=
                go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc v1.3.0/go.mod h1:keUU7UfnwWTWpJ+FWnyqmogPa82nuU5VUANFq49hlMY=
                go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp v1.3.0/go.mod h1:QNX1aly8ehqqX1LEa6YniTU7VY9I6R3X/oPxhGdTceE=
                go.opentelemetry.io/otel/metric v0.20.0/go.mod h1:598I5tYlH1vzBjn+BTuhzTCSb/9debfNp6R3s7Pr1eU=
                go.opentelemetry.io/otel/oteltest v0.20.0/go.mod h1:L7bgKf9ZB7qCwT9Up7i9/pn0PWIa9FqQ2IQ8LoxiGnw=
                go.opentelemetry.io/otel/sdk v1.3.0/go.mod h1:rIo4suHNhQwBIPg9axF8V9CA72Wz2mKF1teNrup8yzs=
                go.opentelemetry.io/otel/sdk/export/metric v0.20.0/go.mod h1:h7RBNMsDJ5pmI1zExLi+bJK+Dr8NQCh0qGhm1KDnNlE=
                go.opentelemetry.io/otel/sdk/metric v0.20.0/go.mod h1:knxiS8Xd4E/N+ZqKmUPf3gTTZ4/0TjTXukfxjzSTpHE=
                go.opentelemetry.io/otel/trace v1.3.0/go.mod h1:c/VDhno8888bvQYmbYLqe41/Ldmr/KKunbvWM4/fEjk=
                go.opentelemetry.io/proto/otlp v0.15.0/go.mod h1:H7XAot3MsfNsj7EXtrA2q5xSNQ10UqI405h3+duxN4U=
                go.uber.org/atomic v1.7.0/go.mod h1:fEN4uk6kAWBTFdckzkM89CLk9XfWZrxpCo0nPH17wJc=
                go.uber.org/goleak v1.1.12/go.mod h1:cwTWslyiVhfpKIDGSZEM2HlOvcqm+tG4zioyIeLoqMQ=
                go.uber.org/multierr v1.6.0/go.mod h1:cdWPpRnG4AhwMwsgIHip0KRBQjJy5kYEpYjJxpXp9iU=
                go.uber.org/zap v1.17.0/go.mod h1:MXVU+bhUf/A7Xi2HNOnopQOrmycQ5Ih87HtOu4q5SSo=
                golang.org/x/crypto v0.0.0-20211108221036-ceb1ce70b4fa/go.mod h1:GvvjBRRGRdwPK5ydBHafDWAxML/pGHZbMvKqRZ5+Abc=
                golang.org/x/exp v0.0.0-20220827204233-334a2380cb91/go.mod h1:cyybsKvd6eL0RnXn6p/Grxp8F5bW7iYuBgsNCOHpMYE=
                golang.org/x/image v0.0.0-20220302094943-723b81ca9867/go.mod h1:023OzeP/+EPmXeapQh35lcL3II3LrY8Ic+EFFKVhULM=
                golang.org/x/lint v0.0.0-20210508222113-6edffad5e616/go.mod h1:3xt1FjdF8hUf6vQPIChWIBhFzV8gjjsPE/fR3IyQdNY=
                golang.org/x/mobile v0.0.0-20190719004257-d2bd2a29d028/go.mod h1:E/iHnbuqvinMTCcRqshq8CkpyQDoeVncDDYHnLhea+o=
                golang.org/x/mod v0.8.0/go.mod h1:iBbtSCu2XBx23ZKBPSOrRkjjQPZFPuis4dIYUhu/chs=
                golang.org/x/net v0.8.0/go.mod h1:QVkue5JL9kW//ek3r6jTKnTFis1tRmNAW2P1shuFdJc=
                golang.org/x/oauth2 v0.6.0/go.mod h1:ycmewcwgD4Rpr3eZJLSB4Kyyljb3qDh40vJ8STE5HKw=
                golang.org/x/sync v0.1.0/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sys v0.6.0/go.mod h1:oPkhp1MJrh7nUepCBck5+mAzfO9JrbApNNgaTdGDITg=
                golang.org/x/term v0.6.0/go.mod h1:m6U89DPEgQRMq3DNkDClhWw02AUbt2daBVO4cn4Hv9U=
                golang.org/x/text v0.8.0/go.mod h1:e1OnstbJyHTd6l/uOt8jFFHp6TRDWZR/bV3emEE/zU8=
                golang.org/x/time v0.3.0/go.mod h1:tRJNPiyCQ0inRvYxbN9jk5I+vvW/OXSQhTDSoE431IQ=
                golang.org/x/tools v0.6.0/go.mod h1:Xwgl3UAJ/d3gWutnCtw505GrjyAbvKui8lOU390QaIU=
                golang.org/x/xerrors v0.0.0-20220907171357-04be3eba64a2/go.mod h1:K8+ghG5WaK9qNqU5K3HdILfMLy1f3aNYFI/wnl100a8=
                gonum.org/v1/gonum v0.11.0/go.mod h1:fSG4YDCxxUZQJ7rKsQrj0gMOg00Il0Z96/qMA4bVQhA=
                gonum.org/v1/netlib v0.0.0-20190313105609-8cb42192e0e0/go.mod h1:wa6Ws7BG/ESfp6dHfk7C6KdzKA7wR7u/rKwOGE66zvw=
                gonum.org/v1/plot v0.10.1/go.mod h1:VZW5OlhkL1mysU9vaqNHnsy86inf6Ot+jB3r+BczCEo=
                google.golang.org/api v0.114.0/go.mod h1:ifYI2ZsFK6/uGddGfAD5BMxlnkBqCmqHSDUVi45N5Yg=
                google.golang.org/appengine v1.6.7/go.mod h1:8WjMMxjGQR8xUklV/ARdw2HLXBOI7O7uCIDZVag1xfc=
                google.golang.org/cloud v0.0.0-20151119220103-975617b05ea8/go.mod h1:0H1ncTHf11KCFhTc/+EFRbzSCOZx+VUbRMk55Yv5MYk=
                google.golang.org/genproto v0.0.0-20230331144136-dcfb400f0633/go.mod h1:UUQDJDOlWu4KYeJZffbWgBkS1YFobzKbLVfK69pe0Ak=
                google.golang.org/grpc v1.54.0/go.mod h1:PUSEXI6iWghWaB6lXM4knEgpJNu2qUcKfDtNci3EC2g=
                google.golang.org/grpc/cmd/protoc-gen-go-grpc v1.1.0/go.mod h1:6Kw0yEErY5E/yWrBtf03jp27GLLJujG4z/JK95pnjjw=
                google.golang.org/protobuf v1.30.0/go.mod h1:HV8QOd/L58Z+nl8r43ehVNZIU/HEI6OcFqwMG9pJV4I=
                gopkg.in/airbrake/gobrake.v2 v2.0.9/go.mod h1:/h5ZAUhDkGaJfjzjKLSjv6zCL6O0LLBxU4K+aSYdM/U=
                gopkg.in/alecthomas/kingpin.v2 v2.2.6/go.mod h1:FMv+mEhP44yOT+4EoQTLFTRgOQ1FBLkstjWtayDeSgw=
                gopkg.in/check.v1 v1.0.0-20201130134442-10cb98267c6c/go.mod h1:JHkPIbrfpd72SG/EVd6muEfDQjcINNoR0C8j2r3qZ4Q=
                gopkg.in/cheggaaa/pb.v1 v1.0.25/go.mod h1:V/YB90LKu/1FcN3WVnfiiE5oMCibMjukxqG/qStrOgw=
                gopkg.in/errgo.v1 v1.0.0/go.mod h1:CxwszS/Xz1C49Ucd2i6Zil5UToP1EmyrFhKaMVbg1mk=
                gopkg.in/errgo.v2 v2.1.0/go.mod h1:hNsd1EY+bozCKY1Ytp96fpM3vjJbqLJn88ws8XvfDNI=
                gopkg.in/fsnotify.v1 v1.4.7/go.mod h1:Tz8NjZHkW78fSQdbUxIjBTcgA1z1m8ZHf0WmKUhAMys=
                gopkg.in/gemnasium/logrus-airbrake-hook.v2 v2.1.2/go.mod h1:Xk6kEKp8OKb+X14hQBKWaSkCsqBpgog8nAV2xsGOxlo=
                gopkg.in/httprequest.v1 v1.2.1/go.mod h1:x2Otw96yda5+8+6ZeWwHIJTFkEHWP/qP8pJOzqEtWPM=
                gopkg.in/inf.v0 v0.9.1/go.mod h1:cWUDdTG/fYaXco+Dcufb5Vnc6Gp2YChqWtbxRZE0mXw=
                gopkg.in/ini.v1 v1.51.0/go.mod h1:pNLf8WUiyNEtQjuu5G5vTm06TEv9tsIgeAvK8hOrP4k=
                gopkg.in/mgo.v2 v2.0.0-20190816093944-a6b53ec6cb22/go.mod h1:yeKp02qBN3iKW1OzL3MGk2IdtZzaj7SFntXj72NppTA=
                gopkg.in/natefinch/lumberjack.v2 v2.0.0/go.mod h1:l0ndWWf7gzL7RNwBG7wST/UCcT4T24xpD6X8LsfU/+k=
                gopkg.in/resty.v1 v1.12.0/go.mod h1:mDo4pnntr5jdWRML875a/NmxYqAlA73dVijT2AXvQQo=
                gopkg.in/retry.v1 v1.0.3/go.mod h1:FJkXmWiMaAo7xB+xhvDF59zhfjDWyzmyAxiT4dB688g=
                gopkg.in/square/go-jose.v2 v2.5.1/go.mod h1:M9dMgbHiYLoDGQrXy7OpJDJWiKiU//h+vD76mk0e1AI=
                gopkg.in/tomb.v1 v1.0.0-20141024135613-dd632973f1e7/go.mod h1:dt/ZhP58zS4L8KSrWDmTeBkI65Dw0HsyUHuEVlX15mw=
                gopkg.in/yaml.v2 v2.4.0/go.mod h1:RDklbk79AGWmwhnvt/jBztapEOGDOx6ZbXqjP6csGnQ=
                gopkg.in/yaml.v3 v3.0.1/go.mod h1:K4uyk7z7BCEPqu6E+C64Yfv1cQ7kz7rIZviUmN+EgEM=
                gotest.tools v2.2.0+incompatible/go.mod h1:DsYFclhRJ6vuDpmuTbkuFWG+y2sxOXAzmJt81HFBacw=
                gotest.tools/gotestsum v1.8.2/go.mod h1:6JHCiN6TEjA7Kaz23q1bH0e2Dc3YJjDUZ0DmctFZf+w=
                gotest.tools/v3 v3.3.0/go.mod h1:Mcr9QNxkg0uMvy/YElmo4SpXgJKWgQvYrT7Kw5RzJ1A=
                honnef.co/go/tools v0.1.3/go.mod h1:NgwopIslSNH47DimFoV78dnkksY2EFtX0ajyb3K/las=
                k8s.io/api v0.22.5/go.mod h1:mEhXyLaSD1qTOf40rRiKXkc+2iCem09rWLlFwhCEiAs=
                k8s.io/apimachinery v0.22.5/go.mod h1:xziclGKwuuJ2RM5/rSFQSYAj0zdbci3DH8kj+WvyN0U=
                k8s.io/apiserver v0.22.5/go.mod h1:s2WbtgZAkTKt679sYtSudEQrTGWUSQAPe6MupLnlmaQ=
                k8s.io/client-go v0.22.5/go.mod h1:cs6yf/61q2T1SdQL5Rdcjg9J1ElXSwbjSrW2vFImM4Y=
                k8s.io/code-generator v0.19.7/go.mod h1:lwEq3YnLYb/7uVXLorOJfxg+cUu2oihFhHZ0n9NIla0=
                k8s.io/component-base v0.22.5/go.mod h1:VK3I+TjuF9eaa+Ln67dKxhGar5ynVbwnGrUiNF4MqCI=
                k8s.io/cri-api v0.23.1/go.mod h1:REJE3PSU0h/LOV1APBrupxrEJqnoxZC8KWzkBUHwrK4=
                k8s.io/gengo v0.0.0-20201113003025-83324d819ded/go.mod h1:FiNAH4ZV3gBg2Kwh89tzAEV2be7d5xI0vBa/VySYy3E=
                k8s.io/klog/v2 v2.30.0/go.mod h1:y1WjHnz7Dj687irZUWR/WLkLc5N1YHtjLdmgWjndZn0=
                k8s.io/kube-openapi v0.0.0-20211109043538-20434351676c/go.mod h1:vHXdDvt9+2spS2Rx9ql3I8tycm3H9FDfdUoIuKCefvw=
                k8s.io/kubernetes v1.13.0/go.mod h1:ocZa8+6APFNC2tX1DZASIbocyYT5jHzqFVsY5aoB7Jk=
                k8s.io/utils v0.0.0-20210930125809-cb0fa318a74b/go.mod h1:jPW/WVKK9YHAvNhRxK0md/EJ228hCsBRufyofKtW8HA=
                lukechampine.com/uint128 v1.2.0/go.mod h1:c4eWIwlEGaxC/+H1VguhU4PHXNWDCDMUlWdIWl2j1gk=
                modernc.org/cc/v3 v3.36.3/go.mod h1:NFUHyPn4ekoC/JHeZFfZurN6ixxawE1BnVonP/oahEI=
                modernc.org/ccgo/v3 v3.16.9/go.mod h1:zNMzC9A9xeNUepy6KuZBbugn3c0Mc9TeiJO4lgvkJDo=
                modernc.org/ccorpus v1.11.6/go.mod h1:2gEUTrWqdpH2pXsmTM1ZkjeSrUWDpjMu2T6m29L/ErQ=
                modernc.org/httpfs v1.0.6/go.mod h1:7dosgurJGp0sPaRanU53W4xZYKh14wfzX420oZADeHM=
                modernc.org/libc v1.17.1/go.mod h1:FZ23b+8LjxZs7XtFMbSzL/EhPxNbfZbErxEHc7cbD9s=
                modernc.org/mathutil v1.5.0/go.mod h1:mZW8CKdRPY1v87qxC/wUdX5O1qDzXMP5TH3wjfpga6E=
                modernc.org/memory v1.2.1/go.mod h1:PkUhL0Mugw21sHPeskwZW4D6VscE/GQJOnIpCnW6pSU=
                modernc.org/opt v0.1.3/go.mod h1:WdSiB5evDcignE70guQKxYUl14mgWtbClRi5wmkkTX0=
                modernc.org/sqlite v1.18.1/go.mod h1:6ho+Gow7oX5V+OiOQ6Tr4xeqbx13UZ6t+Fw9IRUG4d4=
                modernc.org/strutil v1.1.3/go.mod h1:MEHNA7PdEnEwLvspRMtWTNnp2nnyvMfkimT1NKNAGbw=
                modernc.org/tcl v1.13.1/go.mod h1:XOLfOwzhkljL4itZkK6T72ckMgvj0BDsnKNdZVUOecw=
                modernc.org/token v1.0.0/go.mod h1:UGzOrNV1mAFSEB63lOFHIpNRUVMvYTc6yu1SMY/XTDM=
                modernc.org/z v1.5.1/go.mod h1:eWFB510QWW5Th9YGZT81s+LwvaAs3Q2yr4sP0rmLkv8=
                rsc.io/binaryregexp v0.2.0/go.mod h1:qTv7/COck+e2FymRvadv62gMdZztPaShugOCi3I+8D8=
                rsc.io/pdf v0.1.1/go.mod h1:n8OzWcQ6Sp37PL01nO98y4iUCRdTGarVfzxY20ICaU4=
                rsc.io/quote/v3 v3.1.0/go.mod h1:yEA65RcK8LyAZtP9Kv3t0HmxON59tX3rD+tICJqUlj0=
                rsc.io/sampler v1.3.0/go.mod h1:T1hPZKmBbMNahiBKFy5HrXp6adAjACjK9JXDnKaTXpA=
                sigs.k8s.io/apiserver-network-proxy/konnectivity-client v0.0.22/go.mod h1:LEScyzhFmoF5pso/YSeBstl57mOzx9xlU9n85RGrDQg=
                sigs.k8s.io/structured-merge-diff/v4 v4.1.2/go.mod h1:j/nl6xW8vLS49O8YvXW1ocPhZawJtm+Yrr7PPRQ0Vg4=
                sigs.k8s.io/yaml v1.2.0/go.mod h1:yfXDCHCao9+ENCvLSE62v9VSji2MKu5jeNfTrofGhJc=
                """
            ),
            "client.go": dedent(
                r"""
                package main

                import (
                    "fmt"
                    "github.com/confluentinc/confluent-kafka-go/kafka"
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
