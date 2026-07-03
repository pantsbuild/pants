# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import sys

import pytest

from pants.core.util_rules.system_binaries import CatBinary
from pants.engine.composite_process import CompositeProcess, Subprocess
from pants.engine.fs import EMPTY_DIGEST, Digest, DigestContents
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(Process, [CompositeProcess]),
            QueryRule(ProcessResult, [Process]),
            QueryRule(DigestContents, [Digest]),
            QueryRule(CatBinary, []),
            QueryRule(Platform, []),
        ],
    )


def test_subprocess_requires_command_or_argv() -> None:
    with pytest.raises(ValueError, match="Exactly one of command and argv must be specified"):
        Subprocess()


def test_subprocess_rejects_both_command_and_argv() -> None:
    with pytest.raises(ValueError, match="Exactly one of command and argv must be specified"):
        Subprocess(command="echo hi", argv=["echo", "hi"])


def test_subprocess_defaults() -> None:
    sub = Subprocess(argv=["cmd"])
    assert sub.input_digest == EMPTY_DIGEST
    assert sub.immutable_input_digests == {}
    assert sub.env == {}
    assert sub.append_only_caches == {}
    assert sub.output_files == ()
    assert sub.output_directories == ()


def test_subprocess_get_command() -> None:
    assert (
        Subprocess(argv=["my-tool", "--flag", "value with spaces"]).get_command()
        == "my-tool --flag 'value with spaces'"
    )

    assert (
        Subprocess(command="cmd1 && cmd2 | tee out.txt").get_command()
        == "cmd1 && cmd2 | tee out.txt"
    )


def _mk_composite_proc(**kwargs) -> CompositeProcess:
    return CompositeProcess(
        subprocesses=[Subprocess(argv=["cmd"])],
        description="test",
        **kwargs,
    )


def test_composite_process_timeout() -> None:
    assert _mk_composite_proc(timeout_seconds=None).timeout_seconds == -1
    assert _mk_composite_proc(timeout_seconds=0).timeout_seconds == -1
    assert _mk_composite_proc(timeout_seconds=-5).timeout_seconds == -1
    assert _mk_composite_proc(timeout_seconds=30).timeout_seconds == 30


def test_to_process_env_same_value_is_allowed(rule_runner: RuleRunner) -> None:
    cp = CompositeProcess(
        description="test",
        subprocesses=[
            Subprocess(argv=["cmd1"], env={"FOO": "bar"}),
            Subprocess(argv=["cmd2"], env={"FOO": "bar"}),
        ],
    )
    process = rule_runner.request(Process, [cp])
    assert process.env.get("FOO") == "bar"


def test_to_process_env_conflict_raises(rule_runner: RuleRunner) -> None:
    cp = CompositeProcess(
        description="test",
        subprocesses=[
            Subprocess(argv=["cmd1"], env={"FOO": "bar"}),
            Subprocess(argv=["cmd2"], env={"FOO": "baz"}),
        ],
    )
    with pytest.raises(Exception, match="FOO"):
        rule_runner.request(Process, [cp])


def test_to_process_append_only_caches_same_value_is_allowed(rule_runner: RuleRunner) -> None:
    cp = CompositeProcess(
        description="test",
        subprocesses=[
            Subprocess(argv=["cmd1"], append_only_caches={"my_cache": ".cache"}),
            Subprocess(argv=["cmd2"], append_only_caches={"my_cache": ".cache"}),
        ],
    )
    process = rule_runner.request(Process, [cp])
    assert process.append_only_caches.get("my_cache") == ".cache"


def test_to_process_append_only_caches_conflict_raises(rule_runner: RuleRunner) -> None:
    cp = CompositeProcess(
        description="test",
        subprocesses=[
            Subprocess(argv=["cmd1"], append_only_caches={"my_cache": ".cache1"}),
            Subprocess(argv=["cmd2"], append_only_caches={"my_cache": ".cache2"}),
        ],
    )
    with pytest.raises(Exception, match="my_cache"):
        rule_runner.request(Process, [cp])


def test_to_process_output_files_concatenated(rule_runner: RuleRunner) -> None:
    cp = CompositeProcess(
        description="test",
        subprocesses=[
            Subprocess(argv=["cmd1"], output_files=["a.txt", "b.txt"]),
            Subprocess(argv=["cmd2"], output_files=["c.txt"]),
        ],
    )
    process = rule_runner.request(Process, [cp])
    assert sorted(process.output_files) == ["a.txt", "b.txt", "c.txt"]


def test_to_process_output_directories_concatenated(rule_runner: RuleRunner) -> None:
    cp = CompositeProcess(
        description="test",
        subprocesses=[
            Subprocess(argv=["cmd1"], output_directories=["dist/", "build/"]),
            Subprocess(argv=["cmd2"], output_directories=["out/"]),
        ],
    )
    process = rule_runner.request(Process, [cp])
    assert sorted(process.output_directories) == ["build/", "dist/", "out/"]


def test_subprocess_command_join(rule_runner: RuleRunner) -> None:
    cp = CompositeProcess(
        description="test",
        subprocesses=[
            Subprocess(argv=["cmd1", "--flag"]),
            Subprocess(command="cmd2 arg1 arg2"),
        ],
    )
    process = rule_runner.request(Process, [cp])
    assert len(process.argv) == 3
    assert process.argv[2] == "cmd1 --flag\ncmd2 arg1 arg2"


def test_composite_process(rule_runner: RuleRunner) -> None:
    cat = rule_runner.request(CatBinary, [])
    composite_process = CompositeProcess(
        description="test CompositeProcess",
        subprocesses=[
            Subprocess(
                argv=[sys.executable, "-c", "with open('hello.txt', 'w') as fp: fp.write('Hello')"]
            ),
            Subprocess(command=f"{cat.path} 'hello.txt'"),
        ],
    )
    process = rule_runner.request(Process, [composite_process])
    result = rule_runner.request(ProcessResult, [process])
    assert result.stdout.decode() == "Hello"
