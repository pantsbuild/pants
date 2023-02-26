# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from textwrap import dedent
from typing import Iterable

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
                require github.com/confluentinc/confluent-kafka-go v1.9.2
                """
            ),
            "go.sum": dedent(
                """\
                cloud.google.com/go v0.26.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
                cloud.google.com/go v0.34.0 h1:eOI3/cP2VTU6uZLDYAoic+eyzzB9YyGmJ7eIjl8rOPg=
                cloud.google.com/go v0.34.0/go.mod h1:aQUYkXzVsufM+DwF1aE+0xfcU+56JwCaLick0ClmMTw=
                github.com/BurntSushi/toml v0.3.1 h1:WXkYYl6Yr3qBf1K79EBnL4mak0OimBfB0XUf9Vl28OQ=
                github.com/BurntSushi/toml v0.3.1/go.mod h1:xHWCNGjB5oqiDr8zfno3MHue2Ht5sIBksp03qcyfWMU=
                github.com/actgardner/gogen-avro/v10 v10.1.0/go.mod h1:o+ybmVjEa27AAr35FRqU98DJu1fXES56uXniYFv4yDA=
                github.com/actgardner/gogen-avro/v10 v10.2.1 h1:z3pOGblRjAJCYpkIJ8CmbMJdksi4rAhaygw0dyXZ930=
                github.com/actgardner/gogen-avro/v10 v10.2.1/go.mod h1:QUhjeHPchheYmMDni/Nx7VB0RsT/ee8YIgGY/xpEQgQ=
                github.com/actgardner/gogen-avro/v9 v9.1.0 h1:YZ5tCwV5xnDZrG4uRDQYT2VAWZCRAG3eyQH/WYR2T6Q=
                github.com/actgardner/gogen-avro/v9 v9.1.0/go.mod h1:nyTj6wPqDJoxM3qdnjcLv+EnMDSDFqE0qDpva2QRmKc=
                github.com/antihax/optional v1.0.0 h1:xK2lYat7ZLaVVcIuj82J8kIro4V6kDe0AUDFboUCwcg=
                github.com/antihax/optional v1.0.0/go.mod h1:uupD/76wgC+ih3iEmQUL+0Ugr19nfwCT1kdvxnR2qWY=
                github.com/census-instrumentation/opencensus-proto v0.2.1 h1:glEXhBS5PSLLv4IXzLA5yPRVX4bilULVyxxbrfOtDAk=
                github.com/census-instrumentation/opencensus-proto v0.2.1/go.mod h1:f6KPmirojxKA12rnyqOA5BBL4O983OfeGPqjHWSTneU=
                github.com/cespare/xxhash/v2 v2.1.1 h1:6MnRN8NT7+YBpUIWxHtefFZOKTAPgGjpQSxqLNn0+qY=
                github.com/cespare/xxhash/v2 v2.1.1/go.mod h1:VGX0DQ3Q6kWi7AoAeZDth3/j3BFtOZR5XLFGgcrjCOs=
                github.com/chzyer/logex v1.1.10 h1:Swpa1K6QvQznwJRcfTfQJmTE72DqScAa40E+fbHEXEE=
                github.com/chzyer/logex v1.1.10/go.mod h1:+Ywpsq7O8HXn0nuIou7OrIPyXbp3wmkHB+jjWRnGsAI=
                github.com/chzyer/readline v0.0.0-20180603132655-2972be24d48e h1:fY5BOSpyZCqRo5OhCuC+XN+r/bBCmeuuJtjz+bCNIf8=
                github.com/chzyer/readline v0.0.0-20180603132655-2972be24d48e/go.mod h1:nSuG5e5PlCu98SY8svDHJxuZscDgtXS6KTTbou5AhLI=
                github.com/chzyer/test v0.0.0-20180213035817-a1ea475d72b1 h1:q763qf9huN11kDQavWsoZXJNW3xEE4JJyHa5Q25/sd8=
                github.com/chzyer/test v0.0.0-20180213035817-a1ea475d72b1/go.mod h1:Q3SI9o4m/ZMnBNeIyt5eFwwo7qiLfzFZmjNmxjkiQlU=
                github.com/client9/misspell v0.3.4 h1:ta993UF76GwbvJcIo3Y68y/M3WxlpEHPWIGDkJYwzJI=
                github.com/client9/misspell v0.3.4/go.mod h1:qj6jICC3Q7zFZvVWo7KLAzC3yx5G7kyvSDkc90ppPyw=
                github.com/cncf/udpa/go v0.0.0-20191209042840-269d4d468f6f/go.mod h1:M8M6+tZqaGXZJjfX53e64911xZQV5JYwmTeXPW+k8Sc=
                github.com/cncf/udpa/go v0.0.0-20201120205902-5459f2c99403/go.mod h1:WmhPx2Nbnhtbo57+VJT5O0JRkEi1Wbu0z5j0R8u5Hbk=
                github.com/cncf/udpa/go v0.0.0-20210930031921-04548b0d99d4 h1:hzAQntlaYRkVSFEfj9OTWlVV1H155FMD8BTKktLv0QI=
                github.com/cncf/udpa/go v0.0.0-20210930031921-04548b0d99d4/go.mod h1:6pvJx4me5XPnfI9Z40ddWsdw2W/uZgQLFXToKeRcDiI=
                github.com/cncf/xds/go v0.0.0-20210922020428-25de7278fc84/go.mod h1:eXthEFrGJvWHgFFCl3hGmgk+/aYT6PnTQLykKQRLhEs=
                github.com/cncf/xds/go v0.0.0-20211001041855-01bcc9b48dfe/go.mod h1:eXthEFrGJvWHgFFCl3hGmgk+/aYT6PnTQLykKQRLhEs=
                github.com/cncf/xds/go v0.0.0-20211011173535-cb28da3451f1 h1:zH8ljVhhq7yC0MIeUL/IviMtY8hx2mK8cN9wEYb8ggw=
                github.com/cncf/xds/go v0.0.0-20211011173535-cb28da3451f1/go.mod h1:eXthEFrGJvWHgFFCl3hGmgk+/aYT6PnTQLykKQRLhEs=
                github.com/confluentinc/confluent-kafka-go v1.9.2 h1:gV/GxhMBUb03tFWkN+7kdhg+zf+QUM+wVkI9zwh770Q=
                github.com/confluentinc/confluent-kafka-go v1.9.2/go.mod h1:ptXNqsuDfYbAE/LBW6pnwWZElUoWxHoV8E43DCrliyo=
                github.com/creack/pty v1.1.9 h1:uDmaGzcdjhF4i/plgjmEsriH11Y0o7RKapEf/LDaM3w=
                github.com/creack/pty v1.1.9/go.mod h1:oKZEueFk5CKHvIhNR5MUki03XCEU+Q6VDXinZuGJ33E=
                github.com/davecgh/go-spew v1.1.0/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
                github.com/davecgh/go-spew v1.1.1 h1:vj9j/u1bqnvCEfJOwUhtlOARqs3+rkHYY13jYWTU97c=
                github.com/davecgh/go-spew v1.1.1/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
                github.com/envoyproxy/go-control-plane v0.9.0/go.mod h1:YTl/9mNaCwkRvm6d1a2C3ymFceY/DCBVvsKhRF0iEA4=
                github.com/envoyproxy/go-control-plane v0.9.1-0.20191026205805-5f8ba28d4473/go.mod h1:YTl/9mNaCwkRvm6d1a2C3ymFceY/DCBVvsKhRF0iEA4=
                github.com/envoyproxy/go-control-plane v0.9.4/go.mod h1:6rpuAdCZL397s3pYoYcLgu1mIlRU8Am5FuJP05cCM98=
                github.com/envoyproxy/go-control-plane v0.9.9-0.20201210154907-fd9021fe5dad/go.mod h1:cXg6YxExXjJnVBQHBLXeUAgxn2UodCpnH306RInaBQk=
                github.com/envoyproxy/go-control-plane v0.9.9-0.20210217033140-668b12f5399d/go.mod h1:cXg6YxExXjJnVBQHBLXeUAgxn2UodCpnH306RInaBQk=
                github.com/envoyproxy/go-control-plane v0.10.2-0.20220325020618-49ff273808a1 h1:xvqufLtNVwAhN8NMyWklVgxnWohi+wtMGQMhtxexlm0=
                github.com/envoyproxy/go-control-plane v0.10.2-0.20220325020618-49ff273808a1/go.mod h1:KJwIaB5Mv44NWtYuAOFCVOjcI94vtpEz2JU/D2v6IjE=
                github.com/envoyproxy/protoc-gen-validate v0.1.0 h1:EQciDnbrYxy13PgWoY8AqoxGiPrpgBZ1R8UNe3ddc+A=
                github.com/envoyproxy/protoc-gen-validate v0.1.0/go.mod h1:iSmxcyjqTsJpI2R4NaDN7+kN2VEUnK/pcBlmesArF7c=
                github.com/frankban/quicktest v1.2.2/go.mod h1:Qh/WofXFeiAFII1aEBu529AtJo6Zg2VHscnEsbBnJ20=
                github.com/frankban/quicktest v1.7.2/go.mod h1:jaStnuzAqU1AJdCO0l53JDCJrVDKcS03DbaAcR7Ks/o=
                github.com/frankban/quicktest v1.10.0/go.mod h1:ui7WezCLWMWxVWr1GETZY3smRy0G4KWq9vcPtJmFl7Y=
                github.com/frankban/quicktest v1.14.0 h1:+cqqvzZV87b4adx/5ayVOaYZ2CrvM4ejQvUdBzPPUss=
                github.com/frankban/quicktest v1.14.0/go.mod h1:NeW+ay9A/U67EYXNFA1nPE8e/tnQv/09mUdL/ijj8og=
                github.com/ghodss/yaml v1.0.0 h1:wQHKEahhL6wmXdzwWG11gIVCkOv05bNOh+Rxn0yngAk=
                github.com/ghodss/yaml v1.0.0/go.mod h1:4dBDuWmgqj2HViK6kFavaiC9ZROes6MMH2rRYeMEF04=
                github.com/golang/glog v0.0.0-20160126235308-23def4e6c14b h1:VKtxabqXZkF25pY9ekfRL6a582T4P37/31XEstQ5p58=
                github.com/golang/glog v0.0.0-20160126235308-23def4e6c14b/go.mod h1:SBH7ygxi8pfUlaOkMMuAQtPIUF8ecWP5IEl/CR7VP2Q=
                github.com/golang/mock v1.1.1 h1:G5FRp8JnTd7RQH5kemVNlMeyXQAztQ3mOWV95KxsXH8=
                github.com/golang/mock v1.1.1/go.mod h1:oTYuIxOrZwtPieC+H1uAHpcLFnEyAGVDL/k47Jfbm0A=
                github.com/golang/protobuf v1.2.0/go.mod h1:6lQm79b+lXiMfvg/cZm0SGofjICqVBUtrP5yJMmIC1U=
                github.com/golang/protobuf v1.3.2/go.mod h1:6lQm79b+lXiMfvg/cZm0SGofjICqVBUtrP5yJMmIC1U=
                github.com/golang/protobuf v1.3.3/go.mod h1:vzj43D7+SQXF/4pzW/hwtAqwc6iTitCiVSaWz5lYuqw=
                github.com/golang/protobuf v1.4.0-rc.1/go.mod h1:ceaxUfeHdC40wWswd/P6IGgMaK3YpKi5j83Wpe3EHw8=
                github.com/golang/protobuf v1.4.0-rc.1.0.20200221234624-67d41d38c208/go.mod h1:xKAWHe0F5eneWXFV3EuXVDTCmh+JuBKY0li0aMyXATA=
                github.com/golang/protobuf v1.4.0-rc.2/go.mod h1:LlEzMj4AhA7rCAGe4KMBDvJI+AwstrUpVNzEA03Pprs=
                github.com/golang/protobuf v1.4.0-rc.4.0.20200313231945-b860323f09d0/go.mod h1:WU3c8KckQ9AFe+yFwt9sWVRKCVIyN9cPHBJSNnbL67w=
                github.com/golang/protobuf v1.4.0/go.mod h1:jodUvKwWbYaEsadDk5Fwe5c77LiNKVO9IDvqG2KuDX0=
                github.com/golang/protobuf v1.4.1/go.mod h1:U8fpvMrcmy5pZrNK1lt4xCsGvpyWQ/VVv6QDs8UjoX8=
                github.com/golang/protobuf v1.4.2/go.mod h1:oDoupMAO8OvCJWAcko0GGGIgR6R6ocIYbsSw735rRwI=
                github.com/golang/protobuf v1.4.3/go.mod h1:oDoupMAO8OvCJWAcko0GGGIgR6R6ocIYbsSw735rRwI=
                github.com/golang/protobuf v1.5.0/go.mod h1:FsONVRAS9T7sI+LIUmWTfcYkHO4aIWwzhcaSAoJOfIk=
                github.com/golang/protobuf v1.5.2 h1:ROPKBNFfQgOUMifHyP+KYbvpjbdoFNs+aK7DXlji0Tw=
                github.com/golang/protobuf v1.5.2/go.mod h1:XVQd3VNwM+JqD3oG2Ue2ip4fOMUkwXdXDdiuN0vRsmY=
                github.com/golang/snappy v0.0.1/go.mod h1:/XxbfmMg8lxefKM7IXC3fBNl/7bRcc72aCRzEWrmP2Q=
                github.com/golang/snappy v0.0.3/go.mod h1:/XxbfmMg8lxefKM7IXC3fBNl/7bRcc72aCRzEWrmP2Q=
                github.com/golang/snappy v0.0.4 h1:yAGX7huGHXlcLOEtBnF4w7FQwA26wojNCwOYAEhLjQM=
                github.com/golang/snappy v0.0.4/go.mod h1:/XxbfmMg8lxefKM7IXC3fBNl/7bRcc72aCRzEWrmP2Q=
                github.com/google/go-cmp v0.2.0/go.mod h1:oXzfMopK8JAjlY9xF4vHSVASa0yLyX7SntLO5aqRK0M=
                github.com/google/go-cmp v0.2.1-0.20190312032427-6f77996f0c42/go.mod h1:8QqcDgzrUqlUb/G2PQTWiueGozuR1884gddMywk6iLU=
                github.com/google/go-cmp v0.3.0/go.mod h1:8QqcDgzrUqlUb/G2PQTWiueGozuR1884gddMywk6iLU=
                github.com/google/go-cmp v0.3.1/go.mod h1:8QqcDgzrUqlUb/G2PQTWiueGozuR1884gddMywk6iLU=
                github.com/google/go-cmp v0.4.0/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                github.com/google/go-cmp v0.5.0/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                github.com/google/go-cmp v0.5.5/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                github.com/google/go-cmp v0.5.6 h1:BKbKCqvP6I+rmFHt06ZmyQtvB8xAkWdhFyr0ZUNZcxQ=
                github.com/google/go-cmp v0.5.6/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                github.com/google/gofuzz v1.0.0 h1:A8PeW59pxE9IoFRqBp37U+mSNaQoZ46F1f0f863XSXw=
                github.com/google/gofuzz v1.0.0/go.mod h1:dBl0BpW6vV/+mYPU4Po3pmUjxk6FQPldtuIdl/M65Eg=
                github.com/google/pprof v0.0.0-20211008130755-947d60d73cc0 h1:zHs+jv3LO743/zFGcByu2KmpbliCU2AhjcGgrdTwSG4=
                github.com/google/pprof v0.0.0-20211008130755-947d60d73cc0/go.mod h1:KgnwoLYCZ8IQu3XUZ8Nc/bM9CCZFOyjUNOSygVozoDg=
                github.com/google/uuid v1.1.2/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                github.com/google/uuid v1.2.0 h1:qJYtXnJRWmpe7m/3XlyhrsLrEURqHRM2kxzoxXqyUDs=
                github.com/google/uuid v1.2.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                github.com/grpc-ecosystem/grpc-gateway v1.16.0 h1:gmcG1KaJ57LophUzW0Hy8NmPhnMZb4M0+kPpLofRdBo=
                github.com/grpc-ecosystem/grpc-gateway v1.16.0/go.mod h1:BDjrQk3hbvj6Nolgz8mAMFbcEtjT1g+wF4CSlocrBnw=
                github.com/hamba/avro v1.5.6 h1:/UBljlJ9hLjkcY7PhpI/bFYb4RMEXHEwHr17gAm/+l8=
                github.com/hamba/avro v1.5.6/go.mod h1:3vNT0RLXXpFm2Tb/5KC71ZRJlOroggq1Rcitb6k4Fr8=
                github.com/heetch/avro v0.3.1 h1:i6DyUBDIwzt6Fs78dYBIXYd5XrYUs/ir4+39WbHQhJE=
                github.com/heetch/avro v0.3.1/go.mod h1:4xn38Oz/+hiEUTpbVfGVLfvOg0yKLlRP7Q9+gJJILgA=
                github.com/iancoleman/orderedmap v0.0.0-20190318233801-ac98e3ecb4b0 h1:i462o439ZjprVSFSZLZxcsoAe592sZB1rci2Z8j4wdk=
                github.com/iancoleman/orderedmap v0.0.0-20190318233801-ac98e3ecb4b0/go.mod h1:N0Wam8K1arqPXNWjMo21EXnBPOPp36vB07FNRdD2geA=
                github.com/ianlancetaylor/demangle v0.0.0-20210905161508-09a460cdf81d h1:uGg2frlt3IcT7kbV6LEp5ONv4vmoO2FW4qSO+my/aoM=
                github.com/ianlancetaylor/demangle v0.0.0-20210905161508-09a460cdf81d/go.mod h1:aYm2/VgdVmcIU8iMfdMvDMsRAQjcfZSKFby6HOFvi/w=
                github.com/invopop/jsonschema v0.4.0 h1:Yuy/unfgCnfV5Wl7H0HgFufp/rlurqPOOuacqyByrws=
                github.com/invopop/jsonschema v0.4.0/go.mod h1:O9uiLokuu0+MGFlyiaqtWxwqJm41/+8Nj0lD7A36YH0=
                github.com/jhump/gopoet v0.0.0-20190322174617-17282ff210b3/go.mod h1:me9yfT6IJSlOL3FCfrg+L6yzUEZ+5jW6WHt4Sk+UPUI=
                github.com/jhump/gopoet v0.1.0 h1:gYjOPnzHd2nzB37xYQZxj4EIQNpBrBskRqQQ3q4ZgSg=
                github.com/jhump/gopoet v0.1.0/go.mod h1:me9yfT6IJSlOL3FCfrg+L6yzUEZ+5jW6WHt4Sk+UPUI=
                github.com/jhump/goprotoc v0.5.0 h1:Y1UgUX+txUznfqcGdDef8ZOVlyQvnV0pKWZH08RmZuo=
                github.com/jhump/goprotoc v0.5.0/go.mod h1:VrbvcYrQOrTi3i0Vf+m+oqQWk9l72mjkJCYo7UvLHRQ=
                github.com/jhump/protoreflect v1.11.0/go.mod h1:U7aMIjN0NWq9swDP7xDdoMfRHb35uiuTd3Z9nFXJf5E=
                github.com/jhump/protoreflect v1.12.0 h1:1NQ4FpWMgn3by/n1X0fbeKEUxP1wBt7+Oitpv01HR10=
                github.com/jhump/protoreflect v1.12.0/go.mod h1:JytZfP5d0r8pVNLZvai7U/MCuTWITgrI4tTg7puQFKI=
                github.com/json-iterator/go v1.1.11 h1:uVUAXhF2To8cbw/3xN3pxj6kk7TYKs98NIrTqPlMWAQ=
                github.com/json-iterator/go v1.1.11/go.mod h1:KdQUCv79m/52Kvf8AW2vK1V8akMuk1QjK/uOdHXbAo4=
                github.com/juju/qthttptest v0.1.1 h1:JPju5P5CDMCy8jmBJV2wGLjDItUsx2KKL514EfOYueM=
                github.com/juju/qthttptest v0.1.1/go.mod h1:aTlAv8TYaflIiTDIQYzxnl1QdPjAg8Q8qJMErpKy6A4=
                github.com/julienschmidt/httprouter v1.3.0 h1:U0609e9tgbseu3rBINet9P48AI/D3oJs4dN7jwJOQ1U=
                github.com/julienschmidt/httprouter v1.3.0/go.mod h1:JR6WtHb+2LUe8TCKY3cZOxFyyO8IZAc4RVcycCCAKdM=
                github.com/kr/pretty v0.1.0/go.mod h1:dAy3ld7l9f0ibDNOQOHHMYYIIbhfbHSm3C4ZsoJORNo=
                github.com/kr/pretty v0.2.0/go.mod h1:ipq/a2n7PKx3OHsz4KJII5eveXtPO4qwEXGdVfWzfnI=
                github.com/kr/pretty v0.3.0 h1:WgNl7dwNpEZ6jJ9k1snq4pZsg7DOEN8hP9Xw0Tsjwk0=
                github.com/kr/pretty v0.3.0/go.mod h1:640gp4NfQd8pI5XOwp5fnNeVWj67G7CFk/SaSQn7NBk=
                github.com/kr/pty v1.1.1 h1:VkoXIwSboBpnk99O/KFauAEILuNHv5DVFKZMBN/gUgw=
                github.com/kr/pty v1.1.1/go.mod h1:pFQYn66WHrOpPYNljwOMqo10TkYh1fy3cYio2l3bCsQ=
                github.com/kr/text v0.1.0/go.mod h1:4Jbv+DJW3UT/LiOwJeYQe1efqtUx/iVham/4vfdArNI=
                github.com/kr/text v0.2.0 h1:5Nx0Ya0ZqY2ygV366QzturHI13Jq95ApcVaJBhpS+AY=
                github.com/kr/text v0.2.0/go.mod h1:eLer722TekiGuMkidMxC/pM04lWEeraHUUmBw8l2grE=
                github.com/linkedin/goavro v2.1.0+incompatible h1:DV2aUlj2xZiuxQyvag8Dy7zjY69ENjS66bWkSfdpddY=
                github.com/linkedin/goavro v2.1.0+incompatible/go.mod h1:bBCwI2eGYpUI/4820s67MElg9tdeLbINjLjiM2xZFYM=
                github.com/linkedin/goavro/v2 v2.10.0/go.mod h1:UgQUb2N/pmueQYH9bfqFioWxzYCZXSfF8Jw03O5sjqA=
                github.com/linkedin/goavro/v2 v2.10.1/go.mod h1:UgQUb2N/pmueQYH9bfqFioWxzYCZXSfF8Jw03O5sjqA=
                github.com/linkedin/goavro/v2 v2.11.1 h1:4cuAtbDfqkKnBXp9E+tRkIJGa6W6iAjwonwt8O1f4U0=
                github.com/linkedin/goavro/v2 v2.11.1/go.mod h1:UgQUb2N/pmueQYH9bfqFioWxzYCZXSfF8Jw03O5sjqA=
                github.com/modern-go/concurrent v0.0.0-20180228061459-e0a39a4cb421/go.mod h1:6dJC0mAP4ikYIbvyc7fijjWJddQyLn8Ig3JB5CqoB9Q=
                github.com/modern-go/concurrent v0.0.0-20180306012644-bacd9c7ef1dd h1:TRLaZ9cD/w8PVh93nsPXa1VrQ6jlwL5oN8l14QlcNfg=
                github.com/modern-go/concurrent v0.0.0-20180306012644-bacd9c7ef1dd/go.mod h1:6dJC0mAP4ikYIbvyc7fijjWJddQyLn8Ig3JB5CqoB9Q=
                github.com/modern-go/reflect2 v0.0.0-20180701023420-4b7aa43c6742/go.mod h1:bx2lNnkwVCuqBIxFjflWJWanXIb3RllmbCylyMrvgv0=
                github.com/modern-go/reflect2 v1.0.1 h1:9f412s+6RmYXLWZSEzVVgPGK7C2PphHj5RJrvfx9AWI=
                github.com/modern-go/reflect2 v1.0.1/go.mod h1:bx2lNnkwVCuqBIxFjflWJWanXIb3RllmbCylyMrvgv0=
                github.com/nrwiersma/avro-benchmarks v0.0.0-20210913175520-21aec48c8f76 h1:wDbc54qVQ+C5oQZ8Q5VlMbqEt2hrnev2bC/gIGL3Ksk=
                github.com/nrwiersma/avro-benchmarks v0.0.0-20210913175520-21aec48c8f76/go.mod h1:iKyFMidsk/sVYONJRE372sJuX/QTRPacU7imPqqsu7g=
                github.com/pkg/diff v0.0.0-20210226163009-20ebb0f2a09e h1:aoZm08cpOy4WuID//EZDgcC4zIxODThtZNPirFr42+A=
                github.com/pkg/diff v0.0.0-20210226163009-20ebb0f2a09e/go.mod h1:pJLUxLENpZxwdsKMEsNbx1VGcRFpLqf3715MtcvvzbA=
                github.com/pmezard/go-difflib v1.0.0 h1:4DBwDE0NGyQoBHbLQYPwSUPoCMWR5BEzIk/f1lZbAQM=
                github.com/pmezard/go-difflib v1.0.0/go.mod h1:iKH77koFhYxTK1pcRnkKkqfTogsbg7gZNVY4sRDYZ/4=
                github.com/prometheus/client_model v0.0.0-20190812154241-14fe0d1b01d4 h1:gQz4mCbXsO+nc9n1hCxHcGA3Zx3Eo+UHZoInFGUIXNM=
                github.com/prometheus/client_model v0.0.0-20190812154241-14fe0d1b01d4/go.mod h1:xMI15A0UPsDsEKsMN9yxemIoYk6Tm2C1GtYGdfGttqA=
                github.com/rogpeppe/clock v0.0.0-20190514195947-2896927a307a h1:3QH7VyOaaiUHNrA9Se4YQIRkDTCw1EJls9xTUCaCeRM=
                github.com/rogpeppe/clock v0.0.0-20190514195947-2896927a307a/go.mod h1:4r5QyqhjIWCcK8DO4KMclc5Iknq5qVBAlbYYzAbUScQ=
                github.com/rogpeppe/fastuuid v1.2.0 h1:Ppwyp6VYCF1nvBTXL3trRso7mXMlRrw9ooo375wvi2s=
                github.com/rogpeppe/fastuuid v1.2.0/go.mod h1:jVj6XXZzXRy/MSR5jhDC/2q6DgLz+nrA6LYCDYWNEvQ=
                github.com/rogpeppe/go-internal v1.6.1/go.mod h1:xXDCJY+GAPziupqXw64V24skbSoqbTEfhy4qGm1nDQc=
                github.com/rogpeppe/go-internal v1.8.0 h1:FCbCCtXNOY3UtUuHUYaghJg4y7Fd14rXifAYUAtL9R8=
                github.com/rogpeppe/go-internal v1.8.0/go.mod h1:WmiCO8CzOY8rg0OYDC4/i/2WRWAB6poM+XZ2dLUbcbE=
                github.com/santhosh-tekuri/jsonschema/v5 v5.0.0 h1:TToq11gyfNlrMFZiYujSekIsPd9AmsA2Bj/iv+s4JHE=
                github.com/santhosh-tekuri/jsonschema/v5 v5.0.0/go.mod h1:FKdcjfQW6rpZSnxxUvEA5H/cDPdvJ/SZJQLWWXWGrZ0=
                github.com/stretchr/objx v0.1.0 h1:4G4v2dO3VZwixGIRoQ5Lfboy6nUhCyYzaqnIAPPhYs4=
                github.com/stretchr/objx v0.1.0/go.mod h1:HFkY916IF+rwdDfMAkV7OtwuqBVzrE8GR6GFx+wExME=
                github.com/stretchr/testify v1.3.0/go.mod h1:M5WIy9Dh21IEIfnGCwXGc5bZfKNJtfHm1UVUgZn+9EI=
                github.com/stretchr/testify v1.3.1-0.20190311161405-34c6fa2dc709/go.mod h1:M5WIy9Dh21IEIfnGCwXGc5bZfKNJtfHm1UVUgZn+9EI=
                github.com/stretchr/testify v1.5.1/go.mod h1:5W2xD1RspED5o8YsWQXVCued0rvSQ+mT+I5cxcmMvtA=
                github.com/stretchr/testify v1.7.0/go.mod h1:6Fq8oRcR53rry900zMqJjRRixrwX3KX962/h/Wwjteg=
                github.com/stretchr/testify v1.7.1 h1:5TQK59W5E3v0r2duFAb7P95B6hEeOyEnHRa8MjYSMTY=
                github.com/stretchr/testify v1.7.1/go.mod h1:6Fq8oRcR53rry900zMqJjRRixrwX3KX962/h/Wwjteg=
                github.com/yuin/goldmark v1.1.27 h1:nqDD4MMMQA0lmWq03Z2/myGPYLQoXtmi0rGVs95ntbo=
                github.com/yuin/goldmark v1.1.27/go.mod h1:3hX8gzYuyVAZsxl0MRgGTJEmQBFcNTphYh9decYSb74=
                go.opentelemetry.io/proto/otlp v0.7.0 h1:rwOQPCuKAKmwGKq2aVNnYIibI6wnV7EvzgfTCzcdGg8=
                go.opentelemetry.io/proto/otlp v0.7.0/go.mod h1:PqfVotwruBrMGOCsRd/89rSnXhoiJIqeYNgFYFoEGnI=
                golang.org/x/crypto v0.0.0-20190308221718-c2843e01d9a2/go.mod h1:djNgcEr1/C05ACkg1iLfiJU5Ep61QUkGW8qpdssI0+w=
                golang.org/x/crypto v0.0.0-20191011191535-87dc89f01550/go.mod h1:yigFU9vqHzYiE8UmvKecakEJjdnWj3jj499lnFckfCI=
                golang.org/x/crypto v0.0.0-20200622213623-75b288015ac9 h1:psW17arqaxU48Z5kZ0CQnkZWQJsqcURM6tKiBApRjXI=
                golang.org/x/crypto v0.0.0-20200622213623-75b288015ac9/go.mod h1:LzIPMQfyMNhhGPhUkYOs5KpL4U8rLKemX1yGLhDgUto=
                golang.org/x/exp v0.0.0-20190121172915-509febef88a4 h1:c2HOrn5iMezYjSlGPncknSEr/8x5LELb/ilJbXi9DEA=
                golang.org/x/exp v0.0.0-20190121172915-509febef88a4/go.mod h1:CJ0aWSM057203Lf6IL+f9T1iT9GByDxfZKAQTCR3kQA=
                golang.org/x/lint v0.0.0-20181026193005-c67002cb31c3/go.mod h1:UVdnD1Gm6xHRNCYTkRU2/jEulfH38KcIWyp/GAMgvoE=
                golang.org/x/lint v0.0.0-20190227174305-5b3e6a55c961/go.mod h1:wehouNa3lNwaWXcvxsM5YxQ5yQlVC4a0KAMCusXpPoU=
                golang.org/x/lint v0.0.0-20190313153728-d0100b6bd8b3 h1:XQyxROzUlZH+WIQwySDgnISgOivlhjIEwaQaJEJrrN0=
                golang.org/x/lint v0.0.0-20190313153728-d0100b6bd8b3/go.mod h1:6SW0HCj/g11FgYtHlgUYUwCkIfeOF89ocIRzGO/8vkc=
                golang.org/x/mod v0.2.0 h1:KU7oHjnv3XNWfa5COkzUifxZmxp1TyI7ImMXqFxLwvQ=
                golang.org/x/mod v0.2.0/go.mod h1:s0Qsj1ACt9ePp/hMypM3fl4fZqREWJwdYDEqhRiZZUA=
                golang.org/x/net v0.0.0-20180724234803-3673e40ba225/go.mod h1:mL1N/T3taQHkDXs73rZJwtUhF3w3ftmwwsq0BUmARs4=
                golang.org/x/net v0.0.0-20180826012351-8a410e7b638d/go.mod h1:mL1N/T3taQHkDXs73rZJwtUhF3w3ftmwwsq0BUmARs4=
                golang.org/x/net v0.0.0-20190108225652-1e06a53dbb7e/go.mod h1:mL1N/T3taQHkDXs73rZJwtUhF3w3ftmwwsq0BUmARs4=
                golang.org/x/net v0.0.0-20190213061140-3a22650c66bd/go.mod h1:mL1N/T3taQHkDXs73rZJwtUhF3w3ftmwwsq0BUmARs4=
                golang.org/x/net v0.0.0-20190311183353-d8887717615a/go.mod h1:t9HGtf8HONx5eT2rtn7q6eTqICYqUVnKs3thJo3Qplg=
                golang.org/x/net v0.0.0-20190404232315-eb5bcb51f2a3/go.mod h1:t9HGtf8HONx5eT2rtn7q6eTqICYqUVnKs3thJo3Qplg=
                golang.org/x/net v0.0.0-20190620200207-3b0461eec859/go.mod h1:z5CRVTTTmAJ677TzLLGU+0bjPO0LkuOLi4/5GtJWs/s=
                golang.org/x/net v0.0.0-20200226121028-0de0cce0169b/go.mod h1:z5CRVTTTmAJ677TzLLGU+0bjPO0LkuOLi4/5GtJWs/s=
                golang.org/x/net v0.0.0-20200505041828-1ed23360d12c/go.mod h1:qpuaurCH72eLCgpAm/N6yyVIVM9cpaDIP3A8BGJEC5A=
                golang.org/x/net v0.0.0-20200625001655-4c5254603344/go.mod h1:/O7V0waA8r7cgGh81Ro3o1hOxt32SMVPicZroKQ2sZA=
                golang.org/x/net v0.0.0-20200822124328-c89045814202/go.mod h1:/O7V0waA8r7cgGh81Ro3o1hOxt32SMVPicZroKQ2sZA=
                golang.org/x/net v0.0.0-20201021035429-f5854403a974/go.mod h1:sp8m0HH+o8qH0wwXwYZr8TS3Oi6o0r6Gce1SSxlDquU=
                golang.org/x/net v0.0.0-20210405180319-a5a99cb37ef4 h1:4nGaVu0QrbjT/AK2PRLuQfQuh6DJve+pELhqTdAj3x0=
                golang.org/x/net v0.0.0-20210405180319-a5a99cb37ef4/go.mod h1:p54w0d4576C0XHj96bSt6lcn1PtDYWL6XObtHCRCNQM=
                golang.org/x/oauth2 v0.0.0-20180821212333-d2e6202438be/go.mod h1:N/0e6XlmueqKjAGxoOufVs8QHGRruUQn6yWY3a++T0U=
                golang.org/x/oauth2 v0.0.0-20200107190931-bf48bf16ab8d h1:TzXSXBo42m9gQenoE3b9BGiEpg5IG2JkU5FkPIawgtw=
                golang.org/x/oauth2 v0.0.0-20200107190931-bf48bf16ab8d/go.mod h1:gOpvHmFTYa4IltrdGE7lF6nIHvwfUNPOp7c8zoXwtLw=
                golang.org/x/sync v0.0.0-20180314180146-1d60e4601c6f/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sync v0.0.0-20181108010431-42b317875d0f/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sync v0.0.0-20181221193216-37e7f081c4d4/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sync v0.0.0-20190423024810-112230192c58/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sync v0.0.0-20190911185100-cd5d95a43a6e/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sync v0.0.0-20210220032951-036812b2e83c h1:5KslGYwFpkhGh+Q16bwMP3cOontH8FOep7tGV86Y7SQ=
                golang.org/x/sync v0.0.0-20210220032951-036812b2e83c/go.mod h1:RxMgew5VJxzue5/jJTE5uejpjVlOe/izrB70Jof72aM=
                golang.org/x/sys v0.0.0-20180830151530-49385e6e1522/go.mod h1:STP8DvDyc/dI5b8T5hshtkjS+E42TnysNCUPdjciGhY=
                golang.org/x/sys v0.0.0-20190215142949-d0b11bdaac8a/go.mod h1:STP8DvDyc/dI5b8T5hshtkjS+E42TnysNCUPdjciGhY=
                golang.org/x/sys v0.0.0-20190412213103-97732733099d/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
                golang.org/x/sys v0.0.0-20200323222414-85ca7c5b95cd/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
                golang.org/x/sys v0.0.0-20200930185726-fdedc70b468f/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
                golang.org/x/sys v0.0.0-20201119102817-f84b799fce68/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
                golang.org/x/sys v0.0.0-20210119212857-b64e53b001e4/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
                golang.org/x/sys v0.0.0-20210330210617-4fbd30eecc44/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
                golang.org/x/sys v0.0.0-20210510120138-977fb7262007/go.mod h1:oPkhp1MJrh7nUepCBck5+mAzfO9JrbApNNgaTdGDITg=
                golang.org/x/sys v0.0.0-20211007075335-d3039528d8ac h1:oN6lz7iLW/YC7un8pq+9bOLyXrprv2+DKfkJY+2LJJw=
                golang.org/x/sys v0.0.0-20211007075335-d3039528d8ac/go.mod h1:oPkhp1MJrh7nUepCBck5+mAzfO9JrbApNNgaTdGDITg=
                golang.org/x/term v0.0.0-20201126162022-7de9c90e9dd1 h1:v+OssWQX+hTHEmOBgwxdZxK4zHq3yOs8F9J7mk0PY8E=
                golang.org/x/term v0.0.0-20201126162022-7de9c90e9dd1/go.mod h1:bj7SfCRtBDWHUb9snDiAeCFNEtKQo2Wmx5Cou7ajbmo=
                golang.org/x/text v0.3.0/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
                golang.org/x/text v0.3.2/go.mod h1:bEr9sfX3Q8Zfm5fL9x+3itogRgK3+ptLWKqgva+5dAk=
                golang.org/x/text v0.3.3/go.mod h1:5Zoc/QRtKVWzQhOtBMvqHzDpF6irO9z98xDceosuGiQ=
                golang.org/x/text v0.3.5 h1:i6eZZ+zk0SOf0xgBpEpPD18qWcJda6q1sxt3S0kzyUQ=
                golang.org/x/text v0.3.5/go.mod h1:5Zoc/QRtKVWzQhOtBMvqHzDpF6irO9z98xDceosuGiQ=
                golang.org/x/tools v0.0.0-20180917221912-90fa682c2a6e/go.mod h1:n7NCudcB/nEzxVGmLbDWY5pfWTLqBcC2KZ6jyYvM4mQ=
                golang.org/x/tools v0.0.0-20190114222345-bf090417da8b/go.mod h1:n7NCudcB/nEzxVGmLbDWY5pfWTLqBcC2KZ6jyYvM4mQ=
                golang.org/x/tools v0.0.0-20190226205152-f727befe758c/go.mod h1:9Yl7xja0Znq3iFh3HoIrodX9oNMXvdceNzlUR8zjMvY=
                golang.org/x/tools v0.0.0-20190311212946-11955173bddd/go.mod h1:LCzVGOaR6xXOjkQ3onu1FJEFr0SW1gC7cKk1uF8kGRs=
                golang.org/x/tools v0.0.0-20190524140312-2c0ae7006135/go.mod h1:RgjU9mgBXZiqYHBnxXauZ1Gv1EHHAz9KjViQ78xBX0Q=
                golang.org/x/tools v0.0.0-20191119224855-298f0cb1881e/go.mod h1:b+2E5dAYhXwXZwtnZ6UAqBI28+e2cm9otk0dWdXHAEo=
                golang.org/x/tools v0.0.0-20200505023115-26f46d2f7ef8 h1:BMFHd4OFnFtWX46Xj4DN6vvT1btiBxyq+s0orYBqcQY=
                golang.org/x/tools v0.0.0-20200505023115-26f46d2f7ef8/go.mod h1:EkVYQZoAsY45+roYkvgYkIh4xh/qjgUK9TdY2XT94GE=
                golang.org/x/xerrors v0.0.0-20190717185122-a985d3407aa7/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                golang.org/x/xerrors v0.0.0-20191011141410-1b5146add898/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                golang.org/x/xerrors v0.0.0-20200804184101-5ec99f83aff1 h1:go1bK/D/BFZV2I8cIQd1NKEZ+0owSTG1fDTci4IqFcE=
                golang.org/x/xerrors v0.0.0-20200804184101-5ec99f83aff1/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                google.golang.org/appengine v1.1.0/go.mod h1:EbEs0AVv82hx2wNQdGPgUI5lhzA/G0D9YwlJXL52JkM=
                google.golang.org/appengine v1.4.0 h1:/wp5JvzpHIxhs/dumFmF7BXTf3Z+dd4uXta4kVyO508=
                google.golang.org/appengine v1.4.0/go.mod h1:xpcJRLb0r/rnEns0DIKYYv+WjYCduHsrkT7/EB5XEv4=
                google.golang.org/genproto v0.0.0-20180817151627-c66870c02cf8/go.mod h1:JiN7NxoALGmiZfu7CAH4rXhgtRTLTxftemlI0sWmxmc=
                google.golang.org/genproto v0.0.0-20190819201941-24fa4b261c55/go.mod h1:DMBHOl98Agz4BDEuKkezgsaosCRResVns1a3J2ZsMNc=
                google.golang.org/genproto v0.0.0-20200513103714-09dca8ec2884/go.mod h1:55QSHmfGQM9UVYDPBsyGGes0y52j32PQ3BqQfXhyH3c=
                google.golang.org/genproto v0.0.0-20200526211855-cb27e3aa2013/go.mod h1:NbSheEEYHJ7i3ixzK3sjbqSGDJWnxyFXZblF3eUsNvo=
                google.golang.org/genproto v0.0.0-20220503193339-ba3ae3f07e29 h1:DJUvgAPiJWeMBiT+RzBVcJGQN7bAEWS5UEoMshES9xs=
                google.golang.org/genproto v0.0.0-20220503193339-ba3ae3f07e29/go.mod h1:RAyBrSAP7Fh3Nc84ghnVLDPuV51xc9agzmm4Ph6i0Q4=
                google.golang.org/grpc v1.19.0/go.mod h1:mqu4LbDTu4XGKhr4mRzUsmM4RtVoemTSY81AxZiDr8c=
                google.golang.org/grpc v1.23.0/go.mod h1:Y5yQAOtifL1yxbo5wqy6BxZv8vAUGQwXBOALyacEbxg=
                google.golang.org/grpc v1.25.1/go.mod h1:c3i+UQWmh7LiEpx4sFZnkU36qjEYZ0imhYfXVyQciAY=
                google.golang.org/grpc v1.27.0/go.mod h1:qbnxyOmOxrQa7FizSgH+ReBfzJrCY1pSN7KXBS8abTk=
                google.golang.org/grpc v1.33.1/go.mod h1:fr5YgcSWrqhRRxogOsw7RzIpsmvOZ6IcH4kBYTpR3n0=
                google.golang.org/grpc v1.36.0/go.mod h1:qjiiYl8FncCW8feJPdyg3v6XW24KsRHe+dy9BAGRRjU=
                google.golang.org/grpc v1.38.0/go.mod h1:NREThFqKR1f3iQ6oBuvc5LadQuXVGo9rkm5ZGrQdJfM=
                google.golang.org/grpc v1.46.0 h1:oCjezcn6g6A75TGoKYBPgKmVBLexhYLM6MebdrPApP8=
                google.golang.org/grpc v1.46.0/go.mod h1:vN9eftEi1UMyUsIF80+uQXhHjbXYbm0uXoFCACuMGWk=
                google.golang.org/protobuf v0.0.0-20200109180630-ec00e32a8dfd/go.mod h1:DFci5gLYBciE7Vtevhsrf46CRTquxDuWsQurQQe4oz8=
                google.golang.org/protobuf v0.0.0-20200221191635-4d8936d0db64/go.mod h1:kwYJMbMJ01Woi6D6+Kah6886xMZcty6N08ah7+eCXa0=
                google.golang.org/protobuf v0.0.0-20200228230310-ab0ca4ff8a60/go.mod h1:cfTl7dwQJ+fmap5saPgwCLgHXTUD7jkjRqWcaiX5VyM=
                google.golang.org/protobuf v1.20.1-0.20200309200217-e05f789c0967/go.mod h1:A+miEFZTKqfCUM6K7xSMQL9OKL/b6hQv+e19PK+JZNE=
                google.golang.org/protobuf v1.21.0/go.mod h1:47Nbq4nVaFHyn7ilMalzfO3qCViNmqZ2kzikPIcrTAo=
                google.golang.org/protobuf v1.22.0/go.mod h1:EGpADcykh3NcUnDUJcl1+ZksZNG86OlYog2l/sGQquU=
                google.golang.org/protobuf v1.23.0/go.mod h1:EGpADcykh3NcUnDUJcl1+ZksZNG86OlYog2l/sGQquU=
                google.golang.org/protobuf v1.23.1-0.20200526195155-81db48ad09cc/go.mod h1:EGpADcykh3NcUnDUJcl1+ZksZNG86OlYog2l/sGQquU=
                google.golang.org/protobuf v1.25.0/go.mod h1:9JNX74DMeImyA3h4bdi1ymwjUzf21/xIlbajtzgsN7c=
                google.golang.org/protobuf v1.26.0-rc.1/go.mod h1:jlhhOSvTdKEhbULTjvd4ARK9grFBp09yW+WbY/TyQbw=
                google.golang.org/protobuf v1.26.0/go.mod h1:9q0QmTI4eRPtz6boOQmLYwt+qCgq0jsYwAQnmE0givc=
                google.golang.org/protobuf v1.27.1/go.mod h1:9q0QmTI4eRPtz6boOQmLYwt+qCgq0jsYwAQnmE0givc=
                google.golang.org/protobuf v1.28.0 h1:w43yiav+6bVFTBQFZX0r7ipe9JQ1QsbMgHwbBziscLw=
                google.golang.org/protobuf v1.28.0/go.mod h1:HV8QOd/L58Z+nl8r43ehVNZIU/HEI6OcFqwMG9pJV4I=
                gopkg.in/avro.v0 v0.0.0-20171217001914-a730b5802183 h1:PGIdqvwfpMUyUP+QAlAnKTSWQ671SmYjoou2/5j7HXk=
                gopkg.in/avro.v0 v0.0.0-20171217001914-a730b5802183/go.mod h1:FvqrFXt+jCsyQibeRv4xxEJBL5iG2DDW5aeJwzDiq4A=
                gopkg.in/check.v1 v0.0.0-20161208181325-20d25e280405/go.mod h1:Co6ibVJAznAaIkqp8huTwlJQCZ016jof/cbN4VW5Yz0=
                gopkg.in/check.v1 v1.0.0-20180628173108-788fd7840127/go.mod h1:Co6ibVJAznAaIkqp8huTwlJQCZ016jof/cbN4VW5Yz0=
                gopkg.in/check.v1 v1.0.0-20190902080502-41f04d3bba15 h1:YR8cESwS4TdDjEe65xsg0ogRM/Nc3DYOhEAlW+xobZo=
                gopkg.in/check.v1 v1.0.0-20190902080502-41f04d3bba15/go.mod h1:Co6ibVJAznAaIkqp8huTwlJQCZ016jof/cbN4VW5Yz0=
                gopkg.in/errgo.v1 v1.0.0 h1:n+7XfCyygBFb8sEjg6692xjC6Us50TFRO54+xYUEwjE=
                gopkg.in/errgo.v1 v1.0.0/go.mod h1:CxwszS/Xz1C49Ucd2i6Zil5UToP1EmyrFhKaMVbg1mk=
                gopkg.in/errgo.v2 v2.1.0 h1:0vLT13EuvQ0hNvakwLuFZ/jYrLp5F3kcWHXdRggjCE8=
                gopkg.in/errgo.v2 v2.1.0/go.mod h1:hNsd1EY+bozCKY1Ytp96fpM3vjJbqLJn88ws8XvfDNI=
                gopkg.in/httprequest.v1 v1.2.1 h1:pEPLMdF/gjWHnKxLpuCYaHFjc8vAB2wrYjXrqDVC16E=
                gopkg.in/httprequest.v1 v1.2.1/go.mod h1:x2Otw96yda5+8+6ZeWwHIJTFkEHWP/qP8pJOzqEtWPM=
                gopkg.in/mgo.v2 v2.0.0-20190816093944-a6b53ec6cb22 h1:VpOs+IwYnYBaFnrNAeB8UUWtL3vEUnzSCL1nVjPhqrw=
                gopkg.in/mgo.v2 v2.0.0-20190816093944-a6b53ec6cb22/go.mod h1:yeKp02qBN3iKW1OzL3MGk2IdtZzaj7SFntXj72NppTA=
                gopkg.in/retry.v1 v1.0.3 h1:a9CArYczAVv6Qs6VGoLMio99GEs7kY9UzSF9+LD+iGs=
                gopkg.in/retry.v1 v1.0.3/go.mod h1:FJkXmWiMaAo7xB+xhvDF59zhfjDWyzmyAxiT4dB688g=
                gopkg.in/yaml.v2 v2.2.2/go.mod h1:hI93XBmqTisBFMUTm0b8Fm+jr3Dg1NNxqwp+5A1VGuI=
                gopkg.in/yaml.v2 v2.2.3/go.mod h1:hI93XBmqTisBFMUTm0b8Fm+jr3Dg1NNxqwp+5A1VGuI=
                gopkg.in/yaml.v2 v2.2.7/go.mod h1:hI93XBmqTisBFMUTm0b8Fm+jr3Dg1NNxqwp+5A1VGuI=
                gopkg.in/yaml.v2 v2.2.8 h1:obN1ZagJSUGI0Ek/LBmuj4SNLPfIny3KsKFopxRdj10=
                gopkg.in/yaml.v2 v2.2.8/go.mod h1:hI93XBmqTisBFMUTm0b8Fm+jr3Dg1NNxqwp+5A1VGuI=
                gopkg.in/yaml.v3 v3.0.0-20200313102051-9f266ea9e77c/go.mod h1:K4uyk7z7BCEPqu6E+C64Yfv1cQ7kz7rIZviUmN+EgEM=
                gopkg.in/yaml.v3 v3.0.0-20210107192922-496545a6307b h1:h8qDotaEPuJATrMmW04NCwg7v22aHH28wwpauUhK9Oo=
                gopkg.in/yaml.v3 v3.0.0-20210107192922-496545a6307b/go.mod h1:K4uyk7z7BCEPqu6E+C64Yfv1cQ7kz7rIZviUmN+EgEM=
                honnef.co/go/tools v0.0.0-20190102054323-c2f93a96b099/go.mod h1:rf3lG4BRIbNafJWhAfAdb/ePZxsR/4RtNHQocxwk9r4=
                honnef.co/go/tools v0.0.0-20190523083050-ea95bdfd59fc h1:/hemPrYIhOhy8zYrNj+069zDB68us2sMGsfkFJO0iZs=
                honnef.co/go/tools v0.0.0-20190523083050-ea95bdfd59fc/go.mod h1:rf3lG4BRIbNafJWhAfAdb/ePZxsR/4RtNHQocxwk9r4=
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
