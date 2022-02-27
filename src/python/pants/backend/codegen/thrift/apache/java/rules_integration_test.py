# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.thrift.apache.java.rules import GenerateJavaFromThriftRequest
from pants.backend.codegen.thrift.apache.java.rules import rules as apache_thrift_java_rules
from pants.backend.codegen.thrift.apache.rules import rules as apache_thrift_rules
from pants.backend.codegen.thrift.rules import rules as thrift_rules
from pants.backend.codegen.thrift.target_types import (
    ThriftSourceField,
    ThriftSourcesGeneratorTarget,
)
from pants.build_graph.address import Address
from pants.core.util_rules import source_files, stripped_source_files
from pants.engine.internals import graph
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.source import source_root
from pants.testutil.rule_runner import RuleRunner, logging


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *thrift_rules(),
            *apache_thrift_rules(),
            *apache_thrift_java_rules(),
            *source_files.rules(),
            *source_root.rules(),
            *graph.rules(),
            *stripped_source_files.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateJavaFromThriftRequest]),
        ],
        target_types=[ThriftSourcesGeneratorTarget],
    )


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
        [GenerateJavaFromThriftRequest(thrift_sources.snapshot, tgt)],
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

    assert_gen(
        Address("src/thrift/dir1", relative_file_path="f.thrift"),
        [
            "src/thrift/Person.java",
        ],
    )
    assert_gen(
        Address("src/thrift/dir1", relative_file_path="f2.thrift"),
        [
            "src/thrift/ManagedPerson.java",
        ],
    )
    # TODO: Fix package namespacing?
    assert_gen(
        Address("src/thrift/dir2", relative_file_path="g.thrift"),
        [
            "src/thrift/ManagedPersonWrapper.java",
        ],
    )
    # TODO: Fix namespacing.
    assert_gen(
        Address("tests/thrift/test_thrifts", relative_file_path="f.thrift"),
        [
            "tests/thrift/Executive.java",
        ],
    )
