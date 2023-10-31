# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from pathlib import Path
from textwrap import dedent

import pytest

from pants.core.util_rules import system_binaries
from pants.core.util_rules.system_binaries import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryShims,
    BinaryShimsRequest,
)
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *system_binaries.rules(),
            QueryRule(BinaryPaths, [BinaryPathRequest]),
            QueryRule(BinaryShims, [BinaryShimsRequest]),
            QueryRule(DigestContents, [Digest]),
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


def test_binary_shims_request(rule_runner: RuleRunner) -> None:
    result = rule_runner.request(
        BinaryShims,
        [
            BinaryShimsRequest.for_binaries(
                "ls",
                rationale="test the binary shims feature",
                search_path=("/usr/bin", "/bin"),
            )
        ],
    )

    contents = rule_runner.request(DigestContents, [result.digest])
    assert len(contents) == 1

    binary_shim = contents[0]
    assert binary_shim.path == "ls"
    assert binary_shim.is_executable
    assert re.match(
        dedent(
            """\
            #!(/usr)?/bin/bash
            exec "(/usr)?/bin/ls" "\\$@"
            """
        ),
        binary_shim.content.decode(),
    )


def test_binary_shims_paths(rule_runner: RuleRunner, tmp_path: Path) -> None:
    binary_path_abs = str(tmp_path / "bin" / "mybin")
    result = rule_runner.request(
        BinaryShims,
        [
            BinaryShimsRequest.for_paths(
                BinaryPath(binary_path_abs),
                rationale="test the binary shims feature",
            )
        ],
    )

    contents = rule_runner.request(DigestContents, [result.digest])
    assert len(contents) == 1

    binary_shim = contents[0]
    assert binary_shim.path == "mybin"
    assert binary_shim.is_executable
    assert re.match(
        dedent(
            f"""\
            #!(/usr)?/bin/bash
            exec "{binary_path_abs}" "\\$@"
            """
        ),
        binary_shim.content.decode(),
    )
