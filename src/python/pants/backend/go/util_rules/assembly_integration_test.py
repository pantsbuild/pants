# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
import platform
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals import package_binary
from pants.backend.go.goals.package_binary import GoBinaryFieldSet
from pants.backend.go.target_types import GoBinaryTarget, GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.build_pkg import BuildGoPackageRequest, FallibleBuiltGoPackage
from pants.core.goals.package import BuiltPackage
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import temporary_dir


@pytest.fixture()
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *assembly.rules(),
            *import_analysis.rules(),
            *package_binary.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *link.rules(),
            *target_type_rules.rules(),
            *third_party_pkg.rules(),
            *sdk.rules(),
            QueryRule(BuiltPackage, (GoBinaryFieldSet,)),
            QueryRule(FallibleBuiltGoPackage, (BuildGoPackageRequest,)),
        ],
        target_types=[
            GoBinaryTarget,
            GoModTarget,
            GoPackageTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def build_package(rule_runner: RuleRunner, binary_target: Target) -> BuiltPackage:
    field_set = GoBinaryFieldSet.create(binary_target)
    result = rule_runner.request(BuiltPackage, [field_set])
    rule_runner.write_digest(result.digest)
    return result


def test_build_package_with_assembly(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/assembly
                go 1.17
                """
            ),
            "main.go": dedent(
                """\
                package main

                import "fmt"

                func main() {
                    fmt.Println(add(1, 2))
                }
                """
            ),
            "add_amd64.go": "package main\nfunc add(x, y int64) int64",
            "add_arm64.go": "package main\nfunc add(x, y int64) int64",
            # Based on https://davidwong.fr/goasm/add.
            "add_amd64.s": dedent(
                """\
                TEXT ·add(SB),$0-24
                    MOVQ  x+0(FP), BX
                    MOVQ  y+8(FP), BP

                    ADDQ  BP, BX
                    MOVQ  BX, ret+16(FP)
                    RET
                """
            ),
            # Based on combining https://davidwong.fr/goasm/add and `go tool compile -S` to get
            # ARM instructions.
            "add_arm64.s": dedent(
                """\
                TEXT ·add(SB),$0-24
                    MOVD  x+0(FP), R0
                    MOVD  y+8(FP), R1

                    ADD   R1, R0, R0
                    MOVD  R0, ret+16(FP)
                    RET
                """
            ),
            "BUILD": dedent(
                """\
                go_mod(name="mod")
                go_package(name="pkg", sources=["*.go", "*.s"])
                go_binary(name="bin")
                """
            ),
        }
    )

    binary_tgt = rule_runner.get_target(Address("", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "bin"

    result = subprocess.run([os.path.join(rule_runner.build_root, "bin")], stdout=subprocess.PIPE)
    assert result.returncode == 0
    assert result.stdout == b"3\n"


def test_build_invalid_package(rule_runner: RuleRunner) -> None:
    request = BuildGoPackageRequest(
        import_path="example.com/assembly",
        pkg_name="main",
        dir_path="",
        build_opts=GoBuildOptions(),
        go_files=("add_amd64.go", "add_arm64.go"),
        digest=rule_runner.make_snapshot(
            {
                "add_amd64.go": "package main\nfunc add(x, y int64) int64",
                "add_arm64.go": "package main\nfunc add(x, y int64) int64",
                "add_amd64.s": "INVALID!!!",
                "add_arm64.s": "INVALID!!!",
            }
        ).digest,
        s_files=("add_amd64.s", "add_arm64.s"),
        direct_dependencies=(),
        minimum_go_version=None,
    )
    result = rule_runner.request(FallibleBuiltGoPackage, [request])
    assert result.output is None
    assert result.exit_code == 1
    assert result.stdout == "add_amd64.s:1: unexpected EOF\nasm: assembly of add_amd64.s failed\n"


def test_build_package_with_prebuilt_object_files(rule_runner: RuleRunner) -> None:
    # Compile helper assembly into a prebuilt .syso object file.
    machine = platform.uname().machine
    if machine == "x86_64":
        assembly_text = dedent(
            """\
            /* Apple still insists on underscore prefixes for C function names. */
            #if defined(__APPLE__)
            #define EXT(s) _##s
            #else
            #define EXT(s) s
            #endif
            .align 4
            .globl EXT(fortytwo)
            EXT(fortytwo):
              movl $42, %eax
              ret
            """
        )
    elif machine == "arm64":
        assembly_text = dedent(
            """\
            /* Apple still insists on underscore prefixes for C function names. */
            #if defined(__APPLE__)
            #define EXT(s) _##s
            #else
            #define EXT(s) s
            #endif
            .align 4
            .globl EXT(fortytwo)
            EXT(fortytwo):
              mov x0, #42
              ret
        """
        )
    else:
        pytest.skip(f"Unsupported architecture for test: {machine}")

    with temporary_dir() as tempdir:
        source_path = Path(tempdir) / "fortytwo.S"
        source_path.write_text(assembly_text)
        output_path = source_path.with_suffix(".o")
        subprocess.check_call(["gcc", "-c", "-o", str(output_path), str(source_path)])
        object_bytes = output_path.read_bytes()

    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/syso_files
                go 1.17
                """
            ),
            "main.go": dedent(
                """\
                package main

                import "fmt"

                func main() {
                    fmt.Println(value())
                }
                """
            ),
            "value.go": dedent(
                """\
                package main
                // extern int fortytwo();
                import "C"
                func value() int {
                    return int(C.fortytwo())
                }
                """
            ),
            "value.syso": object_bytes,
            "BUILD": dedent(
                """\
                go_mod(name="mod")
                go_package(name="pkg", sources=["*.go", "*.syso"])
                go_binary(name="bin")
                """
            ),
        }
    )

    binary_tgt = rule_runner.get_target(Address("", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "bin"

    result = subprocess.run([os.path.join(rule_runner.build_root, "bin")], stdout=subprocess.PIPE)
    assert result.returncode == 0
    assert result.stdout == b"42\n"


def test_build_package_using_api_metdata(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/assembly
                go 1.17
                """
            ),
            "main.go": dedent(
                """\
                package main

                import "fmt"

                const MagicValueToBeUsedByAssembly int = 42

                func main() {
                    fmt.Println(add_magic(10))
                }
                """
            ),
            "add_amd64.go": "package main\nfunc add_magic(x int64) int64",
            "add_arm64.go": "package main\nfunc add_magic(x int64) int64",
            "add_amd64.s": dedent(
                """\
                #include "textflag.h"  // for NOSPLIT
                #include "go_asm.h"  // for const_MagicValueToBeUsedByAssembly
                TEXT ·add_magic(SB),NOSPLIT,$0
                    MOVQ  x+0(FP), BX
                    MOVQ  $const_MagicValueToBeUsedByAssembly, BP

                    ADDQ  BP, BX
                    MOVQ  BX, ret+8(FP)
                    RET
                """
            ),
            "add_arm64.s": dedent(
                """\
                #include "textflag.h"  // for NOSPLIT
                #include "go_asm.h"  // for const_MagicValueToBeUsedByAssembly
                TEXT ·add_magic(SB),NOSPLIT,$0
                    MOVD  x+0(FP), R0
                    MOVD  $const_MagicValueToBeUsedByAssembly, R1

                    ADD   R1, R0, R0
                    MOVD  R0, ret+8(FP)
                    RET
                """
            ),
            "BUILD": dedent(
                """\
                go_mod(name="mod")
                go_package(name="pkg", sources=["*.go", "*.s"])
                go_binary(name="bin")
                """
            ),
        }
    )

    binary_tgt = rule_runner.get_target(Address("", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "bin"

    result = subprocess.run([os.path.join(rule_runner.build_root, "bin")], stdout=subprocess.PIPE)
    assert result.returncode == 0
    assert result.stdout == b"52\n"  # should be 10 + the 42 "magic" value


def test_build_package_with_copied_header(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/assembly
                go 1.17
                """
            ),
            "constant_linux.h": dedent(
                """
                #define MAGIC_VALUE 42
                """
            ),
            "constant_darwin.h": dedent(
                """
                #define MAGIC_VALUE 42
                """
            ),
            "main.go": dedent(
                """\
                package main

                import "fmt"

                func main() {
                    fmt.Println(add_magic(10))
                }
                """
            ),
            "add_amd64.go": "package main\nfunc add_magic(x int64) int64",
            "add_arm64.go": "package main\nfunc add_magic(x int64) int64",
            "add_amd64.s": dedent(
                """\
                #include "textflag.h"  // for NOSPLIT
                #include "constant_GOOS.h"  // for MAGIC_VALUE
                TEXT ·add_magic(SB),NOSPLIT,$0
                    MOVQ  x+0(FP), BX
                    MOVQ  $MAGIC_VALUE, BP

                    ADDQ  BP, BX
                    MOVQ  BX, ret+8(FP)
                    RET
                """
            ),
            "add_arm64.s": dedent(
                """\
                #include "textflag.h"  // for NOSPLIT
                #include "constant_GOOS.h"  // for MAGIC_VALUE
                TEXT ·add_magic(SB),NOSPLIT,$0
                    MOVD  x+0(FP), R0
                    MOVD  $MAGIC_VALUE, R1

                    ADD   R1, R0, R0
                    MOVD  R0, ret+8(FP)
                    RET
                """
            ),
            "BUILD": dedent(
                """\
                go_mod(name="mod")
                go_package(name="pkg", sources=["*.go", "*.s", "*.h"])
                go_binary(name="bin")
                """
            ),
        }
    )

    binary_tgt = rule_runner.get_target(Address("", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "bin"

    result = subprocess.run([os.path.join(rule_runner.build_root, "bin")], stdout=subprocess.PIPE)
    assert result.returncode == 0
    assert result.stdout == b"52\n"  # should be 10 + the 42 "magic" value
