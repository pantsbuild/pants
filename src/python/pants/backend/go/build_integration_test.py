# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap
from typing import Iterable, List

import pytest

from pants.backend.go import build
from pants.backend.go.build import GoBinaryFieldSet
from pants.backend.go.target_types import GoBinary, GoPackage
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.util_rules import external_tool, source_files
from pants.engine.fs import FileContent
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[GoBinary, GoPackage],
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *build.rules(),
            QueryRule(BuiltPackage, (GoBinaryFieldSet,)),
        ],
    )


MAIN_SOURCE = FileContent(
    "main.go",
    textwrap.dedent(
        """\
    package main

    import (
    \t"fmt"
    )

    func main() {
    \tfmt.Println("Hello world!")
    }
    """
    ).encode("utf-8"),
)

LIB_SOURCE = FileContent(
    "lib.go",
    textwrap.dedent(
        """\
    package lib

    import (
    \t"fmt"
    )

    func Quote(s string) string {
    \treturn fmt.Sprintf(">> %s <<", s)
    }
    """
    ).encode("utf-8"),
)

MAIN_USING_LIB_SOURCE = FileContent(
    "main.go",
    textwrap.dedent(
        """\
    package main

    import (
    \t"fmt"
    \t"example.com/lib"
    )

    func main() {
    \tfmt.Println(lib.Quote("Hello world!"))
    }
    """
    ).encode("utf-8"),
)


def make_target(
    rule_runner: RuleRunner,
    source_files: List[FileContent],
    *,
    import_path: str,
    dependencies: Iterable[Address] = (),
    target_name: str = "target",
) -> Target:
    for source_file in source_files:
        rule_runner.create_file(f"{source_file.path}", source_file.content.decode())
    source_files_str = ", ".join(f'"{sf.path}"' for sf in source_files)
    deps_str = ", ".join(f'"{addr.spec}"' for addr in dependencies)
    rule_runner.add_to_build_file(
        "",
        f"go_package(name='{target_name}', import_path='{import_path}', sources=[{source_files_str}], dependencies=[{deps_str}])\n",
    )
    return rule_runner.get_target(Address("", target_name=target_name))


def build_package(
    rule_runner: RuleRunner,
    main_target: Target,
) -> BuiltPackage:
    args = ["--backend-packages=pants.backend.go"]
    rule_runner.set_options(args)
    rule_runner.add_to_build_file(
        "", f"go_binary(name='bin', binary_name='foo', main='{main_target.address.spec}')\n"
    )
    go_binary_target = rule_runner.get_target(Address("", target_name="bin"))
    built_package = rule_runner.request(BuiltPackage, (GoBinaryFieldSet.create(go_binary_target),))
    return built_package


def test_package_one_target(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [MAIN_SOURCE], import_path="main")
    built_package = build_package(rule_runner, target)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "foo"


def test_package_with_depenedency(rule_runner: RuleRunner) -> None:
    lib_target = make_target(
        rule_runner, [LIB_SOURCE], import_path="example.com/lib", target_name="lib"
    )
    main_target = make_target(
        rule_runner,
        [MAIN_SOURCE],
        import_path="main",
        dependencies=(lib_target.address,),
        target_name="main",
    )
    built_package = build_package(rule_runner, main_target)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "foo"
