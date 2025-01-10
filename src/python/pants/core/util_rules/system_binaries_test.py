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


def test_no_negative_caching_of_binary_paths_lookups(
    rule_runner: RuleRunner, tmp_path: Path
) -> None:
    MyBin.create(tmp_path / "foo")
    MyBin.create(tmp_path / "bar")

    def find_binary_paths() -> BinaryPaths:
        return rule_runner.request(
            BinaryPaths,
            [
                BinaryPathRequest(
                    binary_name=MyBin.binary_name,
                    search_path=[
                        str(tmp_path / "foo"),
                        str(tmp_path / "bar"),
                    ],
                    check_file_entries=True,
                )
            ],
        )

    binary_paths = find_binary_paths()
    assert len(binary_paths.paths) == 2
    assert binary_paths.paths[0].path == str(tmp_path / "foo" / MyBin.binary_name)
    assert binary_paths.paths[1].path == str(tmp_path / "bar" / MyBin.binary_name)

    # Delete the one of the binaries. It should no longer be found by the binary paths lookup.
    (tmp_path / "foo" / MyBin.binary_name).unlink()

    # Force a new session since the path lookup even though uncached across sessions is still
    # cached in the current session.
    rule_runner.new_session("session2")
    rule_runner.set_options([])

    binary_paths = find_binary_paths()
    assert len(binary_paths.paths) == 1
    assert binary_paths.paths[0].path == str(tmp_path / "bar" / MyBin.binary_name)


def test_merge_and_detection_of_duplicate_binary_paths() -> None:
    # Test merge of duplicate paths where content hash is the same.
    shims_request_1 = BinaryShimsRequest.for_paths(
        BinaryPath("/foo/bar", "abc123"),
        BinaryPath("/abc/def/123", "def456"),
        BinaryPath("/foo/bar", "abc123"),
        rationale="awesomeness",
    )
    assert shims_request_1.paths == (
        BinaryPath("/abc/def/123", "def456"),
        BinaryPath("/foo/bar", "abc123"),
    )

    # Test detection of duplicate pahs with differing content hashes. Exception should be thrown.
    with pytest.raises(ValueError, match="Detected duplicate paths with mismatched content"):
        _ = BinaryShimsRequest.for_paths(
            BinaryPath("/foo/bar", "abc123"),
            BinaryPath("/abc/def/123", "def456"),
            BinaryPath("/foo/bar", "xyz789"),
            rationale="awesomeness",
        )

    # Test paths with no duplication.
    shims_request_2 = BinaryShimsRequest.for_paths(
        BinaryPath("/foo/bar", "abc123"),
        BinaryPath("/abc/def/123", "def456"),
        rationale="awesomeness",
    )
    assert shims_request_2.paths == (
        BinaryPath("/abc/def/123", "def456"),
        BinaryPath("/foo/bar", "abc123"),
    )
