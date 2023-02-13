# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from textwrap import dedent

import pytest

from pants.backend.adhoc.adhoc_tool import GenerateFilesFromAdhocToolRequest
from pants.backend.adhoc.adhoc_tool import rules as adhoc_tool_rules
from pants.backend.adhoc.target_types import AdhocToolTarget
from pants.backend.python.goals.run_python_source import rules as run_python_source_rules
from pants.backend.python.target_types import PythonSourceTarget
from pants.core.target_types import ArchiveTarget, FilesGeneratorTarget
from pants.core.target_types import rules as core_target_type_rules
from pants.core.util_rules import archive, source_files
from pants.core.util_rules.adhoc_process_support import AdhocProcessRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_SNAPSHOT, DigestContents
from pants.engine.process import Process
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *archive.rules(),
            *adhoc_tool_rules(),
            *source_files.rules(),
            *core_target_type_rules(),
            *run_python_source_rules(),
            QueryRule(GeneratedSources, [GenerateFilesFromAdhocToolRequest]),
            QueryRule(Process, [AdhocProcessRequest]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
            QueryRule(TransitiveTargets, [TransitiveTargetsRequest]),
        ],
        target_types=[
            AdhocToolTarget,
            ArchiveTarget,
            FilesGeneratorTarget,
            PythonSourceTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def assert_adhoc_tool_result(
    rule_runner: RuleRunner,
    address: Address,
    expected_contents: dict[str, str],
) -> None:
    generator_type: type[GenerateSourcesRequest] = GenerateFilesFromAdhocToolRequest
    target = rule_runner.get_target(address)
    result = rule_runner.request(GeneratedSources, [generator_type(EMPTY_SNAPSHOT, target)])
    assert result.snapshot.files == tuple(expected_contents)
    contents = rule_runner.request(DigestContents, [result.snapshot.digest])
    for fc in contents:
        assert fc.content == expected_contents[fc.path].encode()


def test_adhoc_tool(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/fruitcake.py": dedent(
                """\
                f = open("fruitcake.txt", "w")
                f.write("fruitcake\\n")
                f.close()
                """
            ),
            "src/BUILD": dedent(
                """\
                python_source(
                    source="fruitcake.py",
                    name="fruitcake",
                )

                adhoc_tool(
                  name="run_fruitcake",
                  runnable=":fruitcake",
                  output_files=["fruitcake.txt"],
                  root_output_directory=".",
                )
                """
            ),
        }
    )

    assert_adhoc_tool_result(
        rule_runner,
        Address("src", target_name="run_fruitcake"),
        expected_contents={"fruitcake.txt": "fruitcake\n"},
    )


def test_adhoc_tool_with_workdir(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/fruitcake.py": dedent(
                """\
                f = open("src/fruitcake.txt", "w")
                f.write("fruitcake\\n")
                f.close()
                """
            ),
            "src/BUILD": dedent(
                """\
                python_source(
                    source="fruitcake.py",
                    name="fruitcake",
                )

                adhoc_tool(
                  name="run_fruitcake",
                  runnable=":fruitcake",
                  output_files=["src/fruitcake.txt"],
                  workdir="/",
                )
                """
            ),
        }
    )

    assert_adhoc_tool_result(
        rule_runner,
        Address("src", target_name="run_fruitcake"),
        expected_contents={"src/fruitcake.txt": "fruitcake\n"},
    )


def test_adhoc_tool_capture_stdout_err(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/fruitcake.py": dedent(
                """\
                import sys
                print("fruitcake")
                print("inconceivable", file=sys.stderr)
                """
            ),
            "src/BUILD": dedent(
                """\
                python_source(
                    source="fruitcake.py",
                    name="fruitcake",
                )

                adhoc_tool(
                  name="run_fruitcake",
                  runnable=":fruitcake",
                  stdout="stdout",
                  stderr="stderr",
                  root_output_directory=".",
                )
                """
            ),
        }
    )

    assert_adhoc_tool_result(
        rule_runner,
        Address("src", target_name="run_fruitcake"),
        expected_contents={
            "stderr": "inconceivable\n",
            "stdout": "fruitcake\n",
        },
    )


@pytest.mark.parametrize(
    ("workdir", "file_location"),
    (
        ("src", "src"),
        (".", "src"),
        ("./", "src"),
        ("/", ""),
        ("", ""),
        ("/src", "src"),
    ),
)
def test_working_directory_special_values(
    rule_runner: RuleRunner, workdir: str, file_location: str
) -> None:
    rule_runner.write_files(
        {
            "src/fruitcake.py": dedent(
                """\
                f = open("fruitcake.txt", "w")
                f.write("fruitcake\\n")
                f.close()
                """
            ),
            "src/BUILD": dedent(
                f"""\
                python_source(
                    source="fruitcake.py",
                    name="fruitcake",
                )

                adhoc_tool(
                  name="run_fruitcake",
                  runnable=":fruitcake",
                  output_files=["fruitcake.txt"],
                  workdir="{workdir}",
                )
                """
            ),
        }
    )

    assert_adhoc_tool_result(
        rule_runner,
        Address("src", target_name="run_fruitcake"),
        expected_contents={os.path.join(file_location, "fruitcake.txt"): "fruitcake\n"},
    )
