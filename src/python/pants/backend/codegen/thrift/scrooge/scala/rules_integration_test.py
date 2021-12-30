# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.thrift.rules import rules as thrift_rules
from pants.backend.codegen.thrift.scrooge.rules import rules as scrooge_rules
from pants.backend.codegen.thrift.scrooge.scala.rules import GenerateScalaFromThriftRequest
from pants.backend.codegen.thrift.scrooge.scala.rules import rules as scrooge_scala_rules
from pants.backend.codegen.thrift.target_types import (
    ThriftSourceField,
    ThriftSourcesGeneratorTarget,
)
from pants.backend.scala import target_types
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.jvm import classpath
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner, logging


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *thrift_rules(),
            *scrooge_rules(),
            *scrooge_scala_rules(),
            *config_files.rules(),
            *classpath.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *scalac_rules(),
            *util_rules(),
            *jdk_rules(),
            *target_types.rules(),
            *stripped_source_files.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateScalaFromThriftRequest]),
        ],
        target_types=[
            ScalaSourceTarget,
            ScalaSourcesGeneratorTarget,
            ThriftSourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options(
        [],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    extra_args: list[str] | None = None,
) -> None:
    args = [f"--source-root-patterns={repr(source_roots)}", *(extra_args or ())]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    tgt = rule_runner.get_target(address)
    thrift_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ThriftSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources,
        [GenerateScalaFromThriftRequest(thrift_sources.snapshot, tgt)],
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


@logging
def test_generates_python(rule_runner: RuleRunner) -> None:
    # This tests a few things:
    #  * We generate the correct file names.
    #  * Thrift files can import other thrift files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    rule_runner.write_files(
        {
            "src/thrift/dir1/f.thrift": dedent(
                """\
                namespace py dir1
                struct Person {
                  1: string name
                  2: i32 id
                  3: string email
                }
                """
            ),
            "src/thrift/dir1/f2.thrift": dedent(
                """\
                namespace py dir1
                include "dir1/f.thrift"
                struct ManagedPerson {
                  1: f.Person employee
                  2: f.Person manager
                }
                """
            ),
            "src/thrift/dir1/BUILD": "thrift_sources()",
            "src/thrift/dir2/g.thrift": dedent(
                """\
                include "dir1/f2.thrift"
                struct ManagedPersonWrapper {
                  1: f2.ManagedPerson managed_person
                }
                """
            ),
            "src/thrift/dir2/BUILD": "thrift_sources(dependencies=['src/thrift/dir1'])",
            # Test another source root.
            "tests/thrift/test_thrifts/f.thrift": dedent(
                """\
                include "dir2/g.thrift"
                struct Executive {
                  1: g.ManagedPersonWrapper managed_person_wrapper
                }
                """
            ),
            "tests/thrift/test_thrifts/BUILD": "thrift_sources(dependencies=['src/thrift/dir2'])",
        }
    )

    def assert_gen(addr: Address, expected: list[str]) -> None:
        assert_files_generated(
            rule_runner,
            addr,
            source_roots=["src/python", "/src/thrift", "/tests/thrift"],
            expected_files=expected,
        )

    # TODO: Why is generated path `src/thrift/thrift`?
    assert_gen(
        Address("src/thrift/dir1", relative_file_path="f.thrift"),
        [
            "src/thrift/thrift/Person.scala",
        ],
    )
    assert_gen(
        Address("src/thrift/dir1", relative_file_path="f2.thrift"),
        [
            "src/thrift/thrift/ManagedPerson.scala",
        ],
    )
    # TODO: Fix package namespacing?
    assert_gen(
        Address("src/thrift/dir2", relative_file_path="g.thrift"),
        [
            "src/thrift/thrift/ManagedPersonWrapper.scala",
        ],
    )
    # TODO: Fix namespacing.
    assert_gen(
        Address("tests/thrift/test_thrifts", relative_file_path="f.thrift"),
        [
            "tests/thrift/thrift/Executive.scala",
        ],
    )
