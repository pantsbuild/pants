# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.adhoc.adhoc_tool import GenerateFilesFromAdhocToolRequest
from pants.backend.adhoc.adhoc_tool import rules as adhoc_tool_rules
from pants.backend.adhoc.run_system_binary import rules as run_system_binary_rules
from pants.backend.adhoc.target_types import AdhocToolTarget, SystemBinaryTarget
from pants.backend.python.goals.run_python_source import rules as run_python_source_rules
from pants.backend.python.target_types import PythonSourceTarget
from pants.core.target_types import ArchiveTarget, FilesGeneratorTarget
from pants.core.target_types import rules as core_target_type_rules
from pants.core.util_rules import archive, source_files
from pants.core.util_rules.adhoc_process_support import AdhocProcessRequest
from pants.core.util_rules.environments import LocalWorkspaceEnvironmentTarget
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
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    rule_runner = PythonRuleRunner(
        rules=[
            *archive.rules(),
            *adhoc_tool_rules(),
            *source_files.rules(),
            *core_target_type_rules(),
            *run_python_source_rules(),
            *run_system_binary_rules(),
            QueryRule(GeneratedSources, [GenerateFilesFromAdhocToolRequest]),
            QueryRule(Process, [AdhocProcessRequest]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
            QueryRule(TransitiveTargets, [TransitiveTargetsRequest]),
        ],
        target_types=[
            SystemBinaryTarget,
            AdhocToolTarget,
            ArchiveTarget,
            FilesGeneratorTarget,
            PythonSourceTarget,
            LocalWorkspaceEnvironmentTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def assert_adhoc_tool_result(
    rule_runner: PythonRuleRunner,
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


def test_adhoc_tool(rule_runner: PythonRuleRunner) -> None:
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


def test_adhoc_tool_with_workdir(rule_runner: PythonRuleRunner) -> None:
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


@pytest.mark.parametrize(
    ("write_dir", "workdir", "root_output_directory", "expected_dir"),
    [
        # various relative paths:
        ("", None, None, "src/"),
        ("dir/", None, None, "src/dir/"),
        ("../", None, None, ""),
        # absolute path
        ("/", None, None, ""),
        # interaction with workdir and root_output_directory:
        ("", "/", None, ""),
        ("dir/", None, ".", "dir/"),
        ("3/", "1/2", "1", "2/3/"),
    ],
)
def test_adhoc_tool_capture_stdout_err(
    rule_runner: PythonRuleRunner,
    write_dir: str,
    workdir: None | str,
    root_output_directory: None | str,
    expected_dir: str,
) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                f"""\
                system_binary(name="bash", binary_name="bash")

                adhoc_tool(
                  name="run_fruitcake",
                  runnable=":bash",
                  args=["-c", "echo fruitcake; echo inconceivable >&2"],
                  stdout="{write_dir}stdout",
                  stderr="{write_dir}stderr",
                  workdir={workdir!r},
                  root_output_directory={root_output_directory!r},
                )
                """
            ),
        }
    )

    assert_adhoc_tool_result(
        rule_runner,
        Address("src", target_name="run_fruitcake"),
        expected_contents={
            f"{expected_dir}stderr": "inconceivable\n",
            f"{expected_dir}stdout": "fruitcake\n",
        },
    )


@pytest.mark.parametrize(
    ("workdir", "expected_dir"),
    (
        ("src", "/src"),
        (".", "/src"),
        ("./", "/src"),
        ("./dst", "/src/dst"),
        ("/", ""),
        ("", ""),
        ("/src", "/src"),
        ("/dst", "/dst"),
        (None, "/src"),
    ),
)
def test_working_directory_special_values(
    rule_runner: PythonRuleRunner, workdir: str, expected_dir: str
) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                f"""\
                system_binary(name="bash", binary_name="bash")
                system_binary(name="sed", binary_name="sed", fingerprint_args=["q"])

                adhoc_tool(
                  name="workdir",
                  runnable=":bash",
                  args=['-c', 'echo $PWD | sed s@^{{chroot}}@@ > out.log'],
                  runnable_dependencies=[":sed"],
                  workdir={workdir!r},
                  output_files=["out.log"],
                  root_output_directory=".",
                )
                """
            ),
        }
    )

    assert_adhoc_tool_result(
        rule_runner,
        Address("src", target_name="workdir"),
        expected_contents={"out.log": f"{expected_dir}\n"},
    )


def test_env_vars(rule_runner: PythonRuleRunner) -> None:
    envvar_value = "clang"
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                f"""\
                system_binary(
                    name="bash",
                    binary_name="bash",
                )

                adhoc_tool(
                  name="envvars",
                  runnable=":bash",
                  args=['-c', 'echo $ENVVAR > out.log'],
                  output_files=["out.log"],
                  extra_env_vars=["ENVVAR={envvar_value}"],
                  root_output_directory=".",
                )
                """
            ),
        }
    )

    assert_adhoc_tool_result(
        rule_runner,
        Address("src", target_name="envvars"),
        expected_contents={"out.log": f"{envvar_value}\n"},
    )


def test_execution_dependencies_and_runnable_dependencies(rule_runner: PythonRuleRunner) -> None:
    file_contents = "example contents"

    rule_runner.write_files(
        {
            # put the runnable in its own directory, so we're sure that the dependencies are
            # resolved relative to the adhoc_tool target
            "a/BUILD": """system_binary(name="bash", binary_name="bash")""",
            "b/BUILD": dedent(
                """
                system_binary(name="renamed_cat", binary_name="cat")
                files(name="f", sources=["f.txt"])

                adhoc_tool(
                  name="deps",
                  runnable="a:bash",
                  args=["-c", "renamed_cat f.txt"],
                  execution_dependencies=[":f"],
                  runnable_dependencies=[":renamed_cat"],
                  stdout="stdout",
                )
                """
            ),
            "b/f.txt": file_contents,
        }
    )

    assert_adhoc_tool_result(
        rule_runner,
        Address("b", target_name="deps"),
        expected_contents={"b/stdout": file_contents},
    )


def test_adhoc_tool_with_workspace_execution(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
            system_binary(name="bash", binary_name="bash")
            adhoc_tool(
                name="make-file",
                runnable=":bash",
                args=["-c", "echo 'workspace' > ./foo.txt"],
                environment="workspace",
                stderr="stderr",
            )
            experimental_workspace_environment(name="workspace")
            """
            )
        }
    )
    rule_runner.set_options(
        ["--environments-preview-names={'workspace': '//:workspace'}"], env_inherit={"PATH"}
    )

    assert_adhoc_tool_result(rule_runner, Address("", target_name="make-file"), {"stderr": ""})

    workspace_output_path = Path(rule_runner.build_root).joinpath("foo.txt")
    assert workspace_output_path.exists()
    assert workspace_output_path.read_text().strip() == "workspace"
