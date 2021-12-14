# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

import pytest

from pants.option.arg_splitter import (
    AllHelp,
    ArgSplitter,
    NoGoalHelp,
    ThingHelp,
    UnknownGoalHelp,
    VersionHelp,
)
from pants.option.scope import ScopeInfo


@pytest.fixture
def known_scope_infos() -> list[ScopeInfo]:
    return [
        ScopeInfo("check", is_goal=True),
        ScopeInfo("test", is_goal=True),
        ScopeInfo("jvm", is_goal=False),
        ScopeInfo("reporting", is_goal=False),
    ]


@pytest.fixture
def splitter(known_scope_infos) -> ArgSplitter:
    return ArgSplitter(known_scope_infos, buildroot=os.getcwd())


def assert_valid_split(
    splitter: ArgSplitter,
    args_str: str,
    *,
    expected_goals: list[str],
    expected_scope_to_flags: dict[str, list[str]],
    expected_specs: list[str],
    expected_passthru: list[str] | None = None,
    expected_is_help: bool = False,
    expected_help_advanced: bool = False,
    expected_help_all: bool = False,
) -> None:
    expected_passthru = expected_passthru or []
    args = shlex.split(args_str)
    split_args = splitter.split_args(args)
    assert expected_goals == split_args.goals
    assert expected_scope_to_flags == split_args.scope_to_flags
    assert expected_specs == split_args.specs
    assert expected_passthru == split_args.passthru
    assert expected_is_help == (splitter.help_request is not None)
    assert expected_help_advanced == (
        isinstance(splitter.help_request, ThingHelp) and splitter.help_request.advanced
    )
    assert expected_help_all == isinstance(splitter.help_request, AllHelp)


def assert_unknown_goal(splitter: ArgSplitter, args_str: str, unknown_goals: list[str]) -> None:
    splitter.split_args(shlex.split(args_str))
    assert isinstance(splitter.help_request, UnknownGoalHelp)
    assert set(unknown_goals) == set(splitter.help_request.unknown_goals)


def test_is_spec(tmp_path: Path, splitter: ArgSplitter, known_scope_infos: list[ScopeInfo]) -> None:
    unambiguous_specs = [
        "a/b/c",
        "a/b/c/",
        "a/b:c",
        "a/b/c.txt",
        ":c",
        "::",
        "a/",
        "./a.txt",
        ".",
        "*",
        "a/b/*.txt",
        "a/b/test*",
        "a/**/*",
        "!",
        "!a/b",
        "!a/b.txt",
        "a/b.txt:tgt",
        "a/b.txt:../tgt",
        "!a/b.txt:tgt",
        "dir#gen",
        "//:tgt#gen",
        "cache.java",
        "cache.tmp.java",
    ]

    directories_vs_goals = ["foo", "a_b_c"]

    # With no directories on disk to tiebreak.
    for spec in directories_vs_goals:
        assert splitter.likely_a_spec(spec) is False
    for s in unambiguous_specs:
        assert splitter.likely_a_spec(s) is True

    # With directories on disk to tiebreak.

    splitter = ArgSplitter(known_scope_infos, tmp_path.as_posix())
    for d in directories_vs_goals:
        (tmp_path / d).mkdir()
        assert splitter.likely_a_spec(d) is True


def goal_split_test(command_line: str, **expected):
    return (
        command_line,
        {
            "expected_goals": ["test"],
            "expected_scope_to_flags": {"": [], "test": []},
            **expected,
        },
    )


@pytest.mark.parametrize(
    "command_line, expected",
    [
        # Basic arg splitting, various flag combos.
        (
            "./pants --check-long-flag -g check -c test -i "
            "src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz",
            dict(
                expected_goals=["check", "test"],
                expected_scope_to_flags={
                    "": ["-g"],
                    "check": ["--long-flag", "-c"],
                    "test": ["-i"],
                },
                expected_specs=["src/java/org/pantsbuild/foo", "src/java/org/pantsbuild/bar:baz"],
            ),
        ),
        (
            "./pants -farg --fff=arg check --gg-gg=arg-arg -g test --iii "
            "--check-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz",
            dict(
                expected_goals=["check", "test"],
                expected_scope_to_flags={
                    "": ["-farg", "--fff=arg"],
                    "check": ["--gg-gg=arg-arg", "-g", "--long-flag"],
                    "test": ["--iii"],
                },
                expected_specs=["src/java/org/pantsbuild/foo", "src/java/org/pantsbuild/bar:baz"],
            ),
        ),
        # Distinguish goals from specs.
        (
            "./pants check test foo::",
            dict(
                expected_goals=["check", "test"],
                expected_scope_to_flags={"": [], "check": [], "test": []},
                expected_specs=["foo::"],
            ),
        ),
        (
            "./pants check test foo::",
            dict(
                expected_goals=["check", "test"],
                expected_scope_to_flags={"": [], "check": [], "test": []},
                expected_specs=["foo::"],
            ),
        ),
        (
            "./pants check test:test",
            dict(
                expected_goals=["check"],
                expected_scope_to_flags={"": [], "check": []},
                expected_specs=["test:test"],
            ),
        ),
        #
        goal_split_test("./pants test test:test", expected_specs=["test:test"]),
        goal_split_test("./pants test ./test", expected_specs=["./test"]),
        goal_split_test("./pants test //test", expected_specs=["//test"]),
        goal_split_test("./pants test ./test.txt", expected_specs=["./test.txt"]),
        goal_split_test("./pants test test/test.txt", expected_specs=["test/test.txt"]),
        goal_split_test("./pants test test/test", expected_specs=["test/test"]),
        goal_split_test("./pants test .", expected_specs=["."]),
        goal_split_test("./pants test *", expected_specs=["*"]),
        goal_split_test("./pants test test/*.txt", expected_specs=["test/*.txt"]),
        goal_split_test("./pants test test/**/*", expected_specs=["test/**/*"]),
        goal_split_test("./pants test !", expected_specs=["!"]),
        goal_split_test("./pants test !a/b", expected_specs=["!a/b"]),
        (
            "./pants test check.java",
            dict(
                expected_goals=["test"],
                expected_scope_to_flags={"": [], "test": []},
                expected_specs=["check.java"],
            ),
        ),
    ],
)
def test_valid_arg_splits(
    splitter: ArgSplitter, command_line: str, expected: dict[str, Any]
) -> None:
    assert_valid_split(
        splitter,
        command_line,
        **expected,
    )


def test_descoping_qualified_flags(splitter: ArgSplitter) -> None:
    assert_valid_split(
        splitter,
        "./pants check test --check-bar --no-test-baz foo/bar",
        expected_goals=["check", "test"],
        expected_scope_to_flags={"": [], "check": ["--bar"], "test": ["--no-baz"]},
        expected_specs=["foo/bar"],
    )
    # Qualified flags don't count as explicit goals.
    assert_valid_split(
        splitter,
        "./pants check --test-bar foo/bar",
        expected_goals=["check"],
        expected_scope_to_flags={"": [], "check": [], "test": ["--bar"]},
        expected_specs=["foo/bar"],
    )


def test_passthru_args(splitter: ArgSplitter) -> None:
    assert_valid_split(
        splitter,
        "./pants test foo/bar -- -t 'this is the arg'",
        expected_goals=["test"],
        expected_scope_to_flags={"": [], "test": []},
        expected_specs=["foo/bar"],
        expected_passthru=["-t", "this is the arg"],
    )
    assert_valid_split(
        splitter,
        "./pants -farg --fff=arg check --gg-gg=arg-arg -g test --iii "
        "--check-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz -- "
        "passthru1 passthru2",
        expected_goals=["check", "test"],
        expected_scope_to_flags={
            "": ["-farg", "--fff=arg"],
            "check": ["--gg-gg=arg-arg", "-g", "--long-flag"],
            "test": ["--iii"],
        },
        expected_specs=["src/java/org/pantsbuild/foo", "src/java/org/pantsbuild/bar:baz"],
        expected_passthru=["passthru1", "passthru2"],
    )


def test_subsystem_flags(splitter: ArgSplitter) -> None:
    # Global subsystem flag in global scope.
    assert_valid_split(
        splitter,
        "./pants --jvm-options=-Dbar=baz test foo:bar",
        expected_goals=["test"],
        expected_scope_to_flags={"": [], "jvm": ["--options=-Dbar=baz"], "test": []},
        expected_specs=["foo:bar"],
    )
    assert_valid_split(
        splitter,
        "./pants test --reporting-template-dir=path foo:bar",
        expected_goals=["test"],
        expected_scope_to_flags={
            "": [],
            "reporting": ["--template-dir=path"],
            "test": [],
        },
        expected_specs=["foo:bar"],
    )


def help_test(command_line: str, **expected):
    return (command_line, {**expected, "expected_passthru": None, "expected_is_help": True})


def help_no_arguments_test(command_line: str, **expected):
    return help_test(
        command_line,
        expected_goals=[],
        expected_scope_to_flags={"": []},
        expected_specs=[],
        **expected,
    )


@pytest.mark.parametrize(
    "command_line, expected",
    [
        help_no_arguments_test("./pants"),
        help_no_arguments_test("./pants help"),
        help_no_arguments_test("./pants -h"),
        help_no_arguments_test("./pants --help"),
        help_no_arguments_test("./pants help-advanced", expected_help_advanced=True),
        help_no_arguments_test("./pants help --help-advanced", expected_help_advanced=True),
        help_no_arguments_test("./pants --help-advanced", expected_help_advanced=True),
        help_no_arguments_test("./pants --help --help-advanced", expected_help_advanced=True),
        help_no_arguments_test("./pants --help-advanced --help", expected_help_advanced=True),
        help_no_arguments_test("./pants help-all", expected_help_all=True),
        help_test(
            "./pants -f",
            expected_goals=[],
            expected_scope_to_flags={"": ["-f"]},
            expected_specs=[],
        ),
        help_test(
            "./pants help check -x",
            expected_goals=["check"],
            expected_scope_to_flags={"": [], "check": ["-x"]},
            expected_specs=[],
        ),
        help_test(
            "./pants help check -x",
            expected_goals=["check"],
            expected_scope_to_flags={"": [], "check": ["-x"]},
            expected_specs=[],
        ),
        help_test(
            "./pants check -h",
            expected_goals=["check"],
            expected_scope_to_flags={"": [], "check": []},
            expected_specs=[],
        ),
        help_test(
            "./pants check --help test",
            expected_goals=["check", "test"],
            expected_scope_to_flags={"": [], "check": [], "test": []},
            expected_specs=[],
        ),
        help_test(
            "./pants test src/foo/bar:baz -h",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": []},
            expected_specs=["src/foo/bar:baz"],
        ),
        help_test(
            "./pants check --help-advanced test",
            expected_goals=["check", "test"],
            expected_scope_to_flags={"": [], "check": [], "test": []},
            expected_specs=[],
            expected_help_advanced=True,
        ),
        help_test(
            "./pants help-advanced check",
            expected_goals=["check"],
            expected_scope_to_flags={"": [], "check": []},
            expected_specs=[],
            expected_help_advanced=True,
        ),
        help_test(
            "./pants check help-all test --help",
            expected_goals=["check", "test"],
            expected_scope_to_flags={"": [], "check": [], "test": []},
            expected_specs=[],
            expected_help_all=True,
        ),
    ],
)
def test_help_detection(splitter: ArgSplitter, command_line: str, expected: dict[str, Any]) -> None:
    assert_valid_split(splitter, command_line, **expected)


def test_version_request_detection(splitter: ArgSplitter) -> None:
    def assert_version_request(args_str: str) -> None:
        splitter.split_args(shlex.split(args_str))
        assert isinstance(splitter.help_request, VersionHelp)

    assert_version_request("./pants -v")
    assert_version_request("./pants -V")
    assert_version_request("./pants --version")
    # A version request supersedes anything else.
    assert_version_request("./pants --version check --foo --bar path/to:tgt")


@pytest.mark.parametrize(
    "command_line, unknown_goals",
    [
        ("./pants foo", ["foo"]),
        ("./pants check foo", ["foo"]),
        ("./pants foo bar baz:qux", ["foo", "bar"]),
        ("./pants foo bar f.ext", ["foo", "bar"]),
        ("./pants foo check bar baz:qux", ["foo", "bar"]),
    ],
)
def test_unknown_goal_detection(
    splitter: ArgSplitter, command_line: str, unknown_goals: list[str]
) -> None:
    assert_unknown_goal(splitter, command_line, unknown_goals)


@pytest.mark.parametrize("extra_args", ("", "foo/bar:baz", "f.ext"))
def test_no_goal_detection(extra_args: str, splitter: ArgSplitter) -> None:
    splitter.split_args(shlex.split(f"./pants {extra_args}"))
    assert isinstance(splitter.help_request, NoGoalHelp)


def test_subsystem_scope_is_unknown_goal(splitter: ArgSplitter) -> None:
    assert_unknown_goal(splitter, "./pants jvm reporting", ["jvm", "reporting"])
