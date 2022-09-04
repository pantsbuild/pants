# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import subprocess
from textwrap import dedent

import pytest

from pants.backend.cc.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.cc.goals import package
from pants.backend.cc.goals.package import CCBinaryFieldSet, CCLibraryFieldSet
from pants.backend.cc.target_types import CCBinaryTarget, CCLibraryTarget, CCSourcesGeneratorTarget
from pants.backend.cc.util_rules import compile, link, toolchain
from pants.core.goals.package import BuiltPackage
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *compile.rules(),
            *dep_inf_rules(),
            *link.rules(),
            *package.rules(),
            *source_files.rules(),
            *toolchain.rules(),
            QueryRule(BuiltPackage, [CCBinaryFieldSet]),
            QueryRule(BuiltPackage, [CCLibraryFieldSet]),
        ],
        target_types=[CCSourcesGeneratorTarget, CCBinaryTarget, CCLibraryTarget],
    )
    # Need to get the PATH so we can access system GCC or Clang
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


BAD_FILE = """\
    int main()
    {
        std::cout << "Hello, world!" << std::endl;
        return 0;
    }
    """

GOOD_FILE = """\
    #include <iostream>

    int main()
    {
        std::cout << "Hello, world!" << std::endl;
        return 0;
    }
    """


def build_library_package(
    rule_runner: RuleRunner,
    target: Target,
) -> BuiltPackage:
    field_set = CCLibraryFieldSet.create(target)
    return rule_runner.request(BuiltPackage, [field_set])


def build_binary_package(
    rule_runner: RuleRunner,
    target: Target,
) -> BuiltPackage:
    field_set = CCBinaryFieldSet.create(target)
    built_package = rule_runner.request(BuiltPackage, [field_set])
    rule_runner.write_digest(built_package.digest)
    return built_package


def test_package_library(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "include/foo/foo.h": dedent(
                """\
                int add(int a, int b);
                """
            ),
            "include/foo/bar.h": dedent(
                """\
                int subtract(int a, int b);
                """
            ),
            "src/foo.c": dedent(
                """\
                #include "foo/foo.h"
                #include "foo/bar.h"
                int add(int a, int b) {
                    return a + b;
                }
                int subtract(int a, int b) {
                    return a - b;
                }
                """
            ),
            "BUILD": dedent(
                """\
                cc_sources(name="sources", sources=["src/foo.c"])
                cc_sources(name="headers", sources=["include/foo/*.h"])
                cc_library(name="lib", dependencies=[":sources", ":headers"], headers=[":headers"])
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="lib"))
    built_package = build_library_package(
        rule_runner,
        tgt,
    )
    relpaths = [
        relpath for artifact in built_package.artifacts if (relpath := artifact.relpath) is not None
    ]
    expected = ["lib", "include/foo/foo.h", "include/foo/bar.h"]
    assert set(expected) == set(relpaths)


def test_package_binary(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "main.cpp": GOOD_FILE,
            "BUILD": dedent(
                """\
                cc_sources(name='t')
                cc_binary(name='bin', dependencies=[':t'])
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="bin"))
    built_package = build_binary_package(
        rule_runner,
        tgt,
    )

    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "bin"

    result = subprocess.run([os.path.join(rule_runner.build_root, "bin")], stdout=subprocess.PIPE)
    assert result.returncode == 0
    assert result.stdout == b"Hello, world!\n"
