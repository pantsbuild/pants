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
        isolated_local_store=True,
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def execute_adhoc_tool(
    rule_runner: PythonRuleRunner,
    address: Address,
) -> GeneratedSources:
    generator_type: type[GenerateSourcesRequest] = GenerateFilesFromAdhocToolRequest
    target = rule_runner.get_target(address)
    return rule_runner.request(GeneratedSources, [generator_type(EMPTY_SNAPSHOT, target)])


def assert_adhoc_tool_result(
    rule_runner: PythonRuleRunner,
    address: Address,
    expected_contents: dict[str, str],
) -> None:
    result = execute_adhoc_tool(rule_runner, address)
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


def test_adhoc_tool_workspace_invalidation_sources(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
            system_binary(name="bash", binary_name="bash")
            adhoc_tool(
              name="cmd",
              runnable=":bash",
              # Use a random value so we can detect when re-execution occurs.
              args=["-c", "echo $RANDOM > out.log"],
              output_files=["out.log"],
              workspace_invalidation_sources=['a-file'],
            )
            """
            ),
            "src/a-file": "",
        }
    )
    address = Address("src", target_name="cmd")

    # Re-executing the initial execution should be cached.
    result1 = execute_adhoc_tool(rule_runner, address)
    result2 = execute_adhoc_tool(rule_runner, address)
    assert result1.snapshot == result2.snapshot

    # Update the hash-only source file's content. The adhoc_tool should be re-executed now.
    (Path(rule_runner.build_root) / "src" / "a-file").write_text("xyzzy")
    result3 = execute_adhoc_tool(rule_runner, address)
    assert result1.snapshot != result3.snapshot


def test_adhoc_tool_path_env_modify_mode(rule_runner: PythonRuleRunner) -> None:
    expected_path = "/bin:/usr/bin"
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                f"""\
            system_binary(name="bash", binary_name="bash")
            system_binary(name="renamed_cat", binary_name="cat")
            adhoc_tool(
                name="shims_prepend",
                runnable=":bash",
                args=["-c", "echo $PATH > foo.txt && renamed_cat foo.txt > path.txt"],
                extra_env_vars=["PATH={expected_path}"],
                output_files=["path.txt"],
                runnable_dependencies=[":renamed_cat"],
                path_env_modify="prepend",
            )
            adhoc_tool(
                name="shims_append",
                runnable=":bash",
                args=["-c", "echo $PATH > foo.txt && renamed_cat foo.txt > path.txt"],
                extra_env_vars=["PATH={expected_path}"],
                output_files=["path.txt"],
                runnable_dependencies=[":renamed_cat"],
                path_env_modify="append",
            )
            adhoc_tool(
                name="shims_off",
                runnable=":bash",
                args=[
                    "-c",
                    '''
                    echo $PATH > path.txt
                    for dir in $( echo "$PATH" | tr ':' '\\n' ) ; do
                      if [ -e "$dir/renamed_cat" ]; then
                        echo "ERROR: Did not expect to find renamed_cat on PATH, but did find it."
                        exit 1
                      fi
                    done
                    '''
                ],
                extra_env_vars=["PATH={expected_path}"],
                output_files=["path.txt"],
                runnable_dependencies=[":renamed_cat"],
                path_env_modify="off",
            )
            """
            )
        }
    )

    def run(target_name: str) -> str:
        result = execute_adhoc_tool(rule_runner, Address("src", target_name=target_name))
        contents = rule_runner.request(DigestContents, [result.snapshot.digest])
        assert len(contents) == 1
        return contents[0].content.decode().strip()

    path_prepend = run("shims_prepend")
    assert path_prepend.endswith(expected_path)
    assert len(path_prepend) > len(expected_path)

    path_append = run("shims_append")
    assert path_append.startswith(expected_path)
    assert len(path_append) > len(expected_path)

    path_off = run("shims_off")
    assert path_off == expected_path


def test_adhoc_tool_cache_scope_session(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
            system_binary(name="bash", binary_name="bash")
            adhoc_tool(
              name="cmd",
              runnable=":bash",
              # Use a random value so we can detect when re-execution occurs.
              args=["-c", "echo $RANDOM > out.log"],
              output_files=["out.log"],
              cache_scope="session",
            )
            """
            ),
            "src/a-file": "",
        }
    )
    address = Address("src", target_name="cmd")

    # Re-executing the initial execution should be cached if in the same session.
    result1 = execute_adhoc_tool(rule_runner, address)
    result2 = execute_adhoc_tool(rule_runner, address)
    assert result1.snapshot == result2.snapshot

    # In a new session, the process should be re-executed.
    rule_runner.new_session("second-session")
    rule_runner.set_options([])
    result3 = execute_adhoc_tool(rule_runner, address)
    assert result2.snapshot != result3.snapshot
