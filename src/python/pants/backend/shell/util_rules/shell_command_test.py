# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.shell.target_types import (
    ShellCommandRunTarget,
    ShellCommandTarget,
    ShellCommandTestTarget,
    ShellSourcesGeneratorTarget,
)
from pants.backend.shell.util_rules.shell_command import (
    GenerateFilesFromShellCommandRequest,
    RunShellCommand,
    ShellCommandProcessFromTargetRequest,
)
from pants.backend.shell.util_rules.shell_command import rules as shell_command_rules
from pants.core.goals.run import RunRequest
from pants.core.target_types import ArchiveTarget, FilesGeneratorTarget, FileSourceField
from pants.core.target_types import rules as core_target_type_rules
from pants.core.util_rules import archive, source_files
from pants.core.util_rules.adhoc_process_support import AdhocProcessRequest
from pants.core.util_rules.environments import LocalWorkspaceEnvironmentTarget
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.environment import EnvironmentName
from pants.engine.fs import EMPTY_SNAPSHOT, DigestContents
from pants.engine.internals.native_engine import IntrinsicError
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import Process, ProcessExecutionFailure
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    MultipleSourcesField,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *archive.rules(),
            *shell_command_rules(),
            *source_files.rules(),
            *core_target_type_rules(),
            QueryRule(GeneratedSources, [GenerateFilesFromShellCommandRequest]),
            QueryRule(Process, [AdhocProcessRequest]),
            QueryRule(Process, [EnvironmentName, ShellCommandProcessFromTargetRequest]),
            QueryRule(RunRequest, [RunShellCommand]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
            QueryRule(TransitiveTargets, [TransitiveTargetsRequest]),
        ],
        target_types=[
            ShellCommandTarget,
            ShellCommandRunTarget,
            ShellCommandTestTarget,
            ShellSourcesGeneratorTarget,
            ArchiveTarget,
            FilesGeneratorTarget,
            LocalWorkspaceEnvironmentTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def assert_shell_command_result(
    rule_runner: RuleRunner,
    address: Address,
    expected_contents: dict[str, str],
) -> None:
    generator_type: type[GenerateSourcesRequest] = GenerateFilesFromShellCommandRequest
    target = rule_runner.get_target(address)
    result = rule_runner.request(GeneratedSources, [generator_type(EMPTY_SNAPSHOT, target)])
    assert result.snapshot.files == tuple(expected_contents)
    contents = rule_runner.request(DigestContents, [result.snapshot.digest])
    for fc in contents:
        assert fc.content == expected_contents[fc.path].encode()


def assert_logged(caplog, expect_logged=None):
    if expect_logged:
        assert len(caplog.records) == len(expect_logged)
        for idx, (lvl, msg) in enumerate(expect_logged):
            log_record = caplog.records[idx]
            assert msg in log_record.message
            assert lvl == log_record.levelno
    else:
        assert not caplog.records


def test_sources_and_files(rule_runner: RuleRunner) -> None:
    MSG = ["Hello shell_command", ", nice cut."]
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="hello",
                  execution_dependencies=[":build-utils", ":files"],
                  tools=[
                    "bash",
                    "cat",
                    "env",
                    "mkdir",
                    "tee",
                  ],
                  output_files=["message.txt"],
                  output_directories=["res"],
                  command="./script.sh",
                  root_output_directory=".",
                )

                files(
                  name="files",
                  sources=["*.txt"],
                )

                shell_sources(name="build-utils")
                """
            ),
            "src/intro.txt": MSG[0],
            "src/outro.txt": MSG[1],
            "src/script.sh": (
                "#!/usr/bin/env bash\n"
                "mkdir res && cat *.txt > message.txt && cat message.txt | tee res/log.txt"
            ),
        }
    )

    # Set script.sh mode to rwxr-xr-x.
    rule_runner.chmod("src/script.sh", 0o755)

    RES = "".join(MSG)
    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="hello"),
        expected_contents={
            "message.txt": RES,
            "res/log.txt": RES,
        },
    )


def test_quotes_command(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="quotes",
                  tools=["echo", "tee"],
                  command='echo "foo bar" | tee out.log',
                  output_files=["out.log"],
                  root_output_directory=".",
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="quotes"),
        expected_contents={"out.log": "foo bar\n"},
    )


def test_chained_shell_commands(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/a/BUILD": dedent(
                """\
                shell_command(
                  name="msg",
                  tools=["echo"],
                  output_files=["../msg"],
                  command="echo 'shell_command:a' > ../msg",
                )
                """
            ),
            "src/b/BUILD": dedent(
                """\
                shell_command(
                  name="msg",
                  tools=["cp", "echo"],
                  output_files=["../msg"],
                  command="echo 'shell_command:b' >> ../msg",
                  execution_dependencies=["src/a:msg"],
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src/a", target_name="msg"),
        expected_contents={"src/msg": "shell_command:a\n"},
    )

    assert_shell_command_result(
        rule_runner,
        Address("src/b", target_name="msg"),
        expected_contents={"src/msg": "shell_command:a\nshell_command:b\n"},
    )


def test_chained_shell_commands_with_workdir(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/a/BUILD": dedent(
                """\
                shell_command(
                  name="msg",
                  tools=["echo"],
                  output_files=["msg"],
                  command="echo 'shell_command:a' > msg",
                  workdir="/",
                )
                """
            ),
            "src/b/BUILD": dedent(
                """\
                shell_command(
                  name="msg",
                  tools=["cp", "echo"],
                  output_files=["msg"],
                  command="echo 'shell_command:b' >> msg",
                  execution_dependencies=["src/a:msg"],
                  workdir="/",
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src/a", target_name="msg"),
        expected_contents={"msg": "shell_command:a\n"},
    )

    assert_shell_command_result(
        rule_runner,
        Address("src/b", target_name="msg"),
        expected_contents={"msg": "shell_command:a\nshell_command:b\n"},
    )


def test_side_effecting_command(caplog, rule_runner: RuleRunner) -> None:
    caplog.set_level(logging.INFO)
    caplog.clear()

    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="side-effect",
                  command="echo 'server started' && echo 'warn msg' >&2",
                  tools=["echo"],
                  log_output=True,
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="side-effect"),
        expected_contents={},
    )

    assert_logged(
        caplog,
        [
            (logging.INFO, "server started\n"),
            (logging.WARNING, "warn msg\n"),
        ],
    )


def test_tool_search_path_stable(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="paths",
                  command="mkdir subdir; cd subdir; ls .",
                  tools=["cd", "ls", "mkdir"],
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="paths"),
        expected_contents={},
    )


def test_shell_command_masquerade_as_a_files_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="content-gen",
                  command="echo contents > contents.txt",
                  tools=["echo"],
                  output_files=["contents.txt"],
                  root_output_directory=".",
                )
                """
            ),
        }
    )

    src_contents = rule_runner.get_target(Address("src", target_name="content-gen"))
    sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                (src_contents[MultipleSourcesField],),
                enable_codegen=True,
                for_sources_types=(FileSourceField,),
            )
        ],
    )

    assert sources.files == ("contents.txt",)
    assert sources.unrooted_files == sources.files

    contents = rule_runner.request(DigestContents, [sources.snapshot.digest])
    assert len(contents) == 1

    fc = contents[0]
    assert fc.path == "contents.txt"
    assert fc.content == b"contents\n"


def test_package_dependencies(caplog, rule_runner: RuleRunner) -> None:
    caplog.set_level(logging.INFO)
    caplog.clear()

    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="msg-gen",
                  command="echo message > msg.txt",
                  tools=["echo"],
                  output_files=["msg.txt"],
                )

                archive(
                  name="msg-archive",
                  format="zip",
                  files=[":msg-gen"],
                )

                shell_command(
                  name="test",
                  command="ls",
                  tools=["ls"],
                  log_output=True,
                  execution_dependencies=[":msg-archive"],
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner, Address("src", target_name="test"), expected_contents={}
    )
    assert_logged(
        caplog,
        [
            (logging.INFO, "msg-archive.zip\n"),
        ],
    )


def test_execution_dependencies(caplog, rule_runner: RuleRunner) -> None:
    caplog.set_level(logging.INFO)
    caplog.clear()

    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="a1",
                  command="echo message > msg.txt",
                  output_files=["msg.txt"],
                  workdir="/",
                )

                shell_command(
                    name="a2",
                    tools=["cat"],
                    command="cat msg.txt > msg2.txt",
                    execution_dependencies=[":a1",],
                    output_files=["msg2.txt",],
                    workdir="/",
                )

                # Fails because runtime dependencies are not exported
                # transitively
                shell_command(
                    name="expect_fail_1",
                    tools=["cat"],
                    command="cat msg.txt",
                    execution_dependencies=[":a2",],
                    workdir="/",
                )

                # Fails because `output_dependencies` are not available at runtime
                shell_command(
                    name="expect_fail_2",
                    tools=["cat"],
                    command="cat msg.txt",
                    execution_dependencies=(),
                    output_dependencies=[":a1"],
                    workdir="/",
                )

                # Fails because `output_dependencies` are not available at runtime
                shell_command(
                    name="expect_fail_3",
                    tools=["cat"],
                    command="cat msg.txt",
                    output_dependencies=[":a1"],
                    workdir="/",
                )


                # Fails because execution dependencies are not fetched transitively
                # even if the root is requested through `output_dependencies`
                shell_command(
                    name="expect_fail_4",
                    tools=["cat"],
                    command="cat msg.txt",
                    output_dependencies=[":a2"],
                    workdir="/",
                )

                # Succeeds because `a1` and `a2` are requested directly
                shell_command(
                    name="expect_success_1",
                    tools=["cat"],
                    command="cat msg.txt msg2.txt > output.txt",
                    execution_dependencies=[":a1", ":a2",],
                    output_files=["output.txt"],
                    workdir="/",
                )

                # Succeeds because `a1` and `a2` are requested directly and `output_dependencies`
                # are made available at runtime
                shell_command(
                    name="expect_success_2",
                    tools=["cat"],
                    command="cat msg.txt msg2.txt > output.txt",
                    execution_dependencies=[":a1", ":a2",],
                    output_dependencies=[":a1", ":a2",],
                    output_files=["output.txt"],
                    workdir="/",
                )
                """
            ),
        }
    )

    for i in range(1, 5):
        with engine_error(ProcessExecutionFailure):
            assert_shell_command_result(
                rule_runner, Address("src", target_name=f"expect_fail_{i}"), expected_contents={}
            )
    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="expect_success_1"),
        expected_contents={"output.txt": "message\nmessage\n"},
    )
    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="expect_success_2"),
        expected_contents={"output.txt": "message\nmessage\n"},
    )


@pytest.mark.parametrize(
    ("workdir", "expected_boot"),
    [
        (None, "cd src; "),
        (".", "cd src; "),
        ("/", ""),
        ("src/with space'n quote", """cd 'src/with space'\"'\"'n quote'; """),
        ("./with space'n quote", """cd 'src/with space'\"'\"'n quote'; """),
    ],
)
def test_run_shell_command_request(
    rule_runner: RuleRunner, workdir: None | str, expected_boot: str
) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                f"""\
                run_shell_command(
                  name="test",
                  command="some cmd string",
                  workdir={workdir!r},
                )
                """
            ),
        }
    )

    args = ("bash", "-c", expected_boot + "some cmd string", "pants run src:test --")

    tgt = rule_runner.get_target(Address("src", target_name="test"))
    run = RunShellCommand.create(tgt)
    request = rule_runner.request(RunRequest, [run])
    assert len(args) == len(request.args)
    # handle the binary name specially, because the path may differ
    assert args[0] in request.args[0]
    for arg, request_arg in zip(args[1:], request.args[1:]):
        assert arg == request_arg


@pytest.mark.parametrize(
    ("tool_name", "should_succeed"),
    (
        ("python3.8", True),
        ("cd", False),
        ("floop", False),
    ),
)
def test_path_populated_with_tools(
    caplog, rule_runner: RuleRunner, tool_name: str, should_succeed: bool
) -> None:
    caplog.set_level(logging.INFO)
    caplog.clear()
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                f"""\
                shell_command(
                  name="tools-populated",
                  tools=["which", "{tool_name}"],
                  command='which {tool_name}',
                  log_output=True,
                )
                """
            )
        }
    )

    try:
        assert_shell_command_result(
            rule_runner,
            Address("src", target_name="tools-populated"),
            expected_contents={},
        )
    except ExecutionError as exerr:
        if should_succeed:
            raise exerr

    if should_succeed:
        assert caplog.records[0].msg.strip().endswith("python3.8")
    else:
        # `which` is silent in `bash` when nothing is found
        assert not caplog.records


def test_shell_command_boot_script(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="boot-script-test",
                  tools=[
                    "python3.8",
                  ],
                  command="./command.script",
                  workdir=".",
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("src", target_name="boot-script-test"))
    res = rule_runner.request(Process, [ShellCommandProcessFromTargetRequest(tgt)])
    assert "bash" in res.argv[0]
    assert res.argv[1] == "-c"
    assert res.argv[2].startswith("cd src &&")
    assert "bash -c" in res.argv[2]
    assert res.argv[2].endswith(shlex.quote("./command.script") + " src:boot-script-test")

    assert "PATH" in res.env


def test_shell_command_boot_script_in_build_root(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                shell_command(
                  name="boot-script-test",
                  tools=[
                    "python3.8",
                  ],
                  command="./command.script",
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="boot-script-test"))
    res = rule_runner.request(Process, [ShellCommandProcessFromTargetRequest(tgt)])
    assert "bash" in res.argv[0]
    assert res.argv[1] == "-c"
    assert "bash -c" in res.argv[2]
    assert res.argv[2].endswith(shlex.quote("./command.script") + " //:boot-script-test")


def test_shell_command_extra_env_vars(caplog, rule_runner: RuleRunner) -> None:
    caplog.set_level(logging.INFO)
    caplog.clear()
    rule_runner.set_options([], env={"FOO": "foo"}, env_inherit={"PATH"})
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="extra-env-test",
                  tools=["echo"],
                  extra_env_vars=["FOO", "HELLO=world", "BAR"],
                  command='echo FOO="$FOO" HELLO="$HELLO" BAR="$BAR"',
                  log_output=True,
                )
                """
            )
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="extra-env-test"),
        expected_contents={},
    )

    assert_logged(caplog, [(logging.INFO, "FOO=foo HELLO=world BAR=\n")])


def test_relative_directories(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="quotes",
                  tools=["echo"],
                  command='echo foosh > ../foosh.txt',
                  output_files=["../foosh.txt"],
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="quotes"),
        expected_contents={"foosh.txt": "foosh\n"},
    )


def test_relative_directories_2(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="quotes",
                  tools=["echo"],
                  command='echo foosh > ../newdir/foosh.txt',
                  output_files=["../newdir/foosh.txt"],
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="quotes"),
        expected_contents={"newdir/foosh.txt": "foosh\n"},
    )


def test_cannot_escape_build_root(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="quotes",
                  tools=["echo"],
                  command='echo foosh > ../../invalid.txt',
                  output_files=["../../invalid.txt"],
                )
                """
            ),
        }
    )

    with engine_error(IntrinsicError):
        assert_shell_command_result(
            rule_runner,
            Address("src", target_name="quotes"),
            expected_contents={"../../invalid.txt": "foosh\n"},
        )


def test_missing_tool_called(
    caplog,
    rule_runner: RuleRunner,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.clear()
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                shell_command(
                  name="gerald-is-not-here",
                  command="gerald hello",
                  log_output=True,
                )
                """
            )
        }
    )

    with pytest.raises(ExecutionError):
        assert_shell_command_result(
            rule_runner,
            Address("src", target_name="gerald-is-not-here"),
            expected_contents={},
        )

    assert "requires the names of any external commands" in caplog.text


def test_env_vars(rule_runner: RuleRunner) -> None:
    envvar_value = "clang"
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                f"""\
                shell_command(
                  name="envvars",
                  tools=[],
                  command='echo $ENVVAR > out.log',
                  output_files=["out.log"],
                  extra_env_vars=["ENVVAR={envvar_value}"],
                  root_output_directory=".",
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="envvars"),
        expected_contents={"out.log": f"{envvar_value}\n"},
    )


_DEFAULT = object()


@pytest.mark.parametrize(
    ("workdir", "expected_dir"),
    [
        ("src", "/src"),
        (".", "/src"),
        ("./", "/src"),
        ("./dst", "/src/dst"),
        ("/", ""),
        ("", ""),
        ("/src", "/src"),
        ("/dst", "/dst"),
        (None, "/src"),
    ],
)
def test_working_directory_special_values(
    rule_runner: RuleRunner, workdir: str | None, expected_dir: str
) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                f"""\
                shell_command(
                  name="workdir",
                  tools=['sed'],
                  command='echo $PWD | sed s@^{{chroot}}@@ > out.log',
                  workdir={workdir!r},
                  output_files=["out.log"],
                  root_output_directory=".",
                )
                """
            ),
        }
    )

    assert_shell_command_result(
        rule_runner,
        Address("src", target_name="workdir"),
        expected_contents={"out.log": f"{expected_dir}\n"},
    )


def test_shell_command_with_workspace_execution(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
            shell_command(
                name="make-file",
                command="echo workspace > foo.txt && echo sandbox > {chroot}/out.log",
                output_files=["out.log"],
                environment="workspace",
            )
            experimental_workspace_environment(name="workspace")
            """
            )
        }
    )
    rule_runner.set_options(
        ["--environments-preview-names={'workspace': '//:workspace'}"],
        env_inherit={"PATH"},
    )

    assert_shell_command_result(
        rule_runner,
        Address("", target_name="make-file"),
        expected_contents={"out.log": "sandbox\n"},
    )
    workspace_output_path = Path(rule_runner.build_root).joinpath("foo.txt")
    assert workspace_output_path.exists()
    assert workspace_output_path.read_text().strip() == "workspace"
