# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
import subprocess
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals import package_binary
from pants.backend.go.goals.package_binary import GoBinaryFieldSet
from pants.backend.go.target_types import GoBinaryTarget, GoModTarget, GoPackageTarget
from pants.backend.go.testutil import gen_module_gomodproxy
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
from pants.core.goals.package import BuiltPackage
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner, engine_error


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


def test_package_simple(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module foo.example.com
                go 1.17
                """
            ),
            "main.go": dedent(
                """\
                package main

                import (
                    "fmt"
                )

                func main() {
                    fmt.Println("Hello world!")
                }
                """
            ),
            "BUILD": dedent(
                """\
                go_mod(name='mod')
                go_package(name='pkg')
                go_binary(name='bin')
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
    assert result.stdout == b"Hello world!\n"


def test_package_third_party_requires_main(rule_runner: RuleRunner) -> None:
    import_path = "pantsbuild.org/go-sample-for-test"
    version = "v0.0.1"

    fake_gomod = gen_module_gomodproxy(
        version,
        import_path,
        (
            (
                "pkg/hello/hello.go",
                dedent(
                    """\
        package hello
        import "fmt"


        func Hello() {
            fmt.Println("Hello world!")
        }
        """
                ),
            ),
            (
                "cmd/hello/main.go",
                dedent(
                    f"""\
        package main
        import "{import_path}/pkg/hello"


        func main() {{
            hello.Hello()
        }}
        """
                ),
            ),
        ),
    )

    fake_gomod.update(
        {
            "BUILD": dedent(
                f"""\
                go_mod(name='mod')
                go_binary(name="bin", main='//:mod#{import_path}/pkg/hello')
                """
            ),
            "go.mod": dedent(
                f"""\
                module go.example.com/foo
                go 1.16

                require (
                \t{import_path} {version}
                )
                """
            ),
        }
    )

    rule_runner.write_files(fake_gomod)

    rule_runner.set_options(
        [
            "--go-test-args=-v -bench=.",
            f"--golang-subprocess-env-vars=GOPROXY=file://{rule_runner.build_root}/go-mod-proxy",
            "--golang-subprocess-env-vars=GOSUMDB=off",
        ],
        env_inherit={"PATH"},
    )

    binary_tgt = rule_runner.get_target(Address("", target_name="bin"))
    with engine_error(ValueError, contains="but uses package name `hello` instead of `main`"):
        build_package(rule_runner, binary_tgt)


def test_package_third_party_can_run(rule_runner: RuleRunner) -> None:
    import_path = "pantsbuild.org/go-sample-for-test"
    version = "v0.0.1"

    fake_gomod = gen_module_gomodproxy(
        version,
        import_path,
        (
            (
                "pkg/hello/hello.go",
                dedent(
                    """\
        package hello
        import "fmt"


        func Hello() {
            fmt.Println("Hello world!")
        }
        """
                ),
            ),
            (
                "cmd/hello/main.go",
                dedent(
                    f"""\
        package main
        import "{import_path}/pkg/hello"


        func main() {{
            hello.Hello()
        }}
        """
                ),
            ),
        ),
    )

    fake_gomod.update(
        {
            "BUILD": dedent(
                f"""\
                go_mod(name='mod')
                go_binary(name="bin", main='//:mod#{import_path}/cmd/hello')
                """
            ),
            "go.mod": dedent(
                f"""\
                module go.example.com/foo
                go 1.16

                require (
                \t{import_path} {version}
                )
                """
            ),
        }
    )

    rule_runner.write_files(fake_gomod)

    rule_runner.set_options(
        [
            "--go-test-args=-v -bench=.",
            f"--golang-subprocess-env-vars=GOPROXY=file://{rule_runner.build_root}/go-mod-proxy",
            "--golang-subprocess-env-vars=GOSUMDB=off",
        ],
        env_inherit={"PATH"},
    )

    binary_tgt = rule_runner.get_target(Address("", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "bin"

    result = subprocess.run([os.path.join(rule_runner.build_root, "bin")], stdout=subprocess.PIPE)
    assert result.returncode == 0
    assert result.stdout == b"Hello world!\n"


def test_package_with_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "lib/lib.go": dedent(
                """\
                package lib

                import (
                    "fmt"
                    "rsc.io/quote"
                )

                func Quote(s string) string {
                    return fmt.Sprintf(">> %s <<", s)
                }

                func GoProverb() string {
                    return quote.Go()
                }
                """
            ),
            "lib/BUILD": "go_package()",
            "main.go": dedent(
                """\
                package main

                import (
                    "fmt"
                    "foo.example.com/lib"
                )

                func main() {
                    fmt.Println(lib.Quote("Hello world!"))
                    fmt.Println(lib.GoProverb())
                }
                """
            ),
            "go.mod": dedent(
                """\
                module foo.example.com
                go 1.17
                require (
                    golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c // indirect
                    rsc.io/quote v1.5.2
                    rsc.io/sampler v1.3.0 // indirect
                )
                """
            ),
            "go.sum": dedent(
                """\
                golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c h1:qgOY6WgZOaTkIIMiVjBQcw93ERBE4m30iBm00nkL0i8=
                golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
                rsc.io/quote v1.5.2 h1:w5fcysjrx7yqtD/aO+QwRjYZOKnaM9Uh2b40tElTs3Y=
                rsc.io/quote v1.5.2/go.mod h1:LzX7hefJvL54yjefDEDHNONDjII0t9xZLPXsUe+TKr0=
                rsc.io/sampler v1.3.0 h1:7uVkIFmeBqHfdjD+gZwtXXI+RODJ2Wc4O7MPEh/QiW4=
                rsc.io/sampler v1.3.0/go.mod h1:T1hPZKmBbMNahiBKFy5HrXp6adAjACjK9JXDnKaTXpA=
                """
            ),
            "BUILD": dedent(
                """\
                go_mod(name='mod')
                go_package(name='pkg')
                go_binary(name='bin')
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
    assert result.stdout == (
        b">> Hello world! <<\n"
        b"Don't communicate by sharing memory, share memory by communicating.\n"
    )
