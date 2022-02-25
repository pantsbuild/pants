# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import pytest

from pants.core.util_rules import system_binaries
from pants.core.util_rules.system_binaries import PythonBinary
from pants.engine.internals.selectors import Get
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import QueryRule, rule
from pants.testutil.rule_runner import RuleRunner


@dataclass(frozen=True)
class PythonBinaryVersion:
    version: str


@rule
async def python_binary_version(python_binary: PythonBinary) -> PythonBinaryVersion:
    process_result = await Get(
        ProcessResult,
        Process(
            argv=(python_binary.path, "--version"),
            description=rf"Running `{python_binary.path} --version`",
        ),
    )
    return PythonBinaryVersion(process_result.stdout.decode())


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*system_binaries.rules(), python_binary_version, QueryRule(PythonBinaryVersion, [])]
    )


def test_python_binary(rule_runner: RuleRunner) -> None:
    rule_runner.set_options((), env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    python_binary_version = rule_runner.request(PythonBinaryVersion, [])
    assert python_binary_version.version.startswith("Python 3.")


def test_interpreter_search_path_file_entries() -> None:
    rule_runner = RuleRunner(
        rules=[*system_binaries.rules(), QueryRule(PythonBinary, input_types=())]
    )
    current_python = os.path.realpath(sys.executable)
    rule_runner.set_options(
        args=[
            f"--python-bootstrap-search-path=[{current_python!r}]",
            f"--python-bootstrap-names=[{os.path.basename(current_python)!r}]",
        ]
    )
    python_binary = rule_runner.request(PythonBinary, inputs=())
    assert current_python == python_binary.path
