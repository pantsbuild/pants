# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from pants.core.util_rules import system_binaries
from pants.core.util_rules.system_binaries import BinaryPathRequest, BinaryPaths, PythonBinary
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
        rules=[
            *system_binaries.rules(),
            python_binary_version,
            QueryRule(PythonBinaryVersion, []),
            QueryRule(BinaryPaths, [BinaryPathRequest]),
        ]
    )


def test_find_binary_non_existent(rule_runner: RuleRunner, tmp_path: Path) -> None:
    binary_paths = rule_runner.request(
        BinaryPaths, [BinaryPathRequest(binary_name="nonexistent-bin", search_path=[str(tmp_path)])]
    )
    assert binary_paths.first_path is None


class MyBin:
    binary_name = "mybin"

    @classmethod
    def create(cls, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        exe = directory / cls.binary_name
        exe.touch(mode=0o755)
        return exe


def test_find_binary_on_path_without_bash(rule_runner: RuleRunner, tmp_path: Path) -> None:
    # Test that locating a binary on a PATH which does not include bash works (by recursing to
    # locate bash first).
    binary_dir_abs = tmp_path / "bin"
    binary_path_abs = MyBin.create(binary_dir_abs)

    binary_paths = rule_runner.request(
        BinaryPaths,
        [BinaryPathRequest(binary_name=MyBin.binary_name, search_path=[str(binary_dir_abs)])],
    )
    assert binary_paths.first_path is not None
    assert binary_paths.first_path.path == str(binary_path_abs)


def test_find_binary_file_path(rule_runner: RuleRunner, tmp_path: Path) -> None:
    binary_path_abs = MyBin.create(tmp_path)

    binary_paths = rule_runner.request(
        BinaryPaths,
        [
            BinaryPathRequest(
                binary_name=MyBin.binary_name,
                search_path=[str(binary_path_abs)],
            )
        ],
    )
    assert binary_paths.first_path is None, "By default, PATH file entries should not be checked."

    binary_paths = rule_runner.request(
        BinaryPaths,
        [
            BinaryPathRequest(
                binary_name=MyBin.binary_name,
                search_path=[str(binary_path_abs)],
                check_file_entries=True,
            )
        ],
    )
    assert binary_paths.first_path is not None
    assert binary_paths.first_path.path == str(binary_path_abs)


def test_find_binary_respects_search_path_order(rule_runner: RuleRunner, tmp_path: Path) -> None:
    binary_path_abs1 = MyBin.create(tmp_path / "bin1")
    binary_path_abs2 = MyBin.create(tmp_path / "bin2")
    binary_path_abs3 = MyBin.create(tmp_path / "bin3")

    binary_paths = rule_runner.request(
        BinaryPaths,
        [
            BinaryPathRequest(
                binary_name=MyBin.binary_name,
                search_path=[
                    str(binary_path_abs1.parent),
                    str(binary_path_abs2),
                    str(binary_path_abs3.parent),
                ],
                check_file_entries=True,
            )
        ],
    )
    assert binary_paths.first_path is not None
    assert binary_paths.first_path.path == str(binary_path_abs1)
    assert [str(p) for p in (binary_path_abs1, binary_path_abs2, binary_path_abs3)] == [
        binary_path.path for binary_path in binary_paths.paths
    ]


def test_python_binary(rule_runner: RuleRunner) -> None:
    rule_runner.set_options((), env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    python_binary_version = rule_runner.request(PythonBinaryVersion, [])
    assert python_binary_version.version.startswith("Python 3.")


def test_python_interpreter_search_path_file_entries() -> None:
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
