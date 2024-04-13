# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

import pytest

from pants.goal.builtins import builtin_goals
from pants.option.arg_splitter import NO_GOAL_NAME, UNKNOWN_GOAL_NAME, ArgSplitter
from pants.option.scope import ScopeInfo


@pytest.fixture
def known_scope_infos() -> list[ScopeInfo]:
    return [
        ScopeInfo("check", is_goal=True),
        ScopeInfo("test", is_goal=True),
        ScopeInfo("jvm", is_goal=False),
        ScopeInfo("reporting", is_goal=False),
        ScopeInfo("bsp", is_goal=True, is_builtin=True),
        # TODO: move help related tests closer to `pants.goal.help` to avoid this cludge.
        *(goal.get_scope_info() for goal in builtin_goals()),
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

    assert expected_is_help == (
        split_args.builtin_goal
        in ("help", "help-advanced", "help-all", UNKNOWN_GOAL_NAME, NO_GOAL_NAME)
    )
    assert expected_help_advanced == ("help-advanced" == split_args.builtin_goal)
    assert expected_help_all == ("help-all" == split_args.builtin_goal)


def assert_unknown_goal(splitter: ArgSplitter, args_str: str, unknown_goals: list[str]) -> None:
    split_args = splitter.split_args(shlex.split(args_str))
    assert UNKNOWN_GOAL_NAME == split_args.builtin_goal
    assert set(unknown_goals) == set(split_args.unknown_goals)


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
        "a/b.txt:tgt",
        "a/b.txt:../tgt",
        "dir#gen",
        "//:tgt#gen",
        "cache.java",
        "cache.tmp.java",
    ]

    directories_vs_goals = ["foo", "a_b_c"]

    # With no directories on disk to tiebreak.
    for spec in directories_vs_goals:
        assert splitter.likely_a_spec(spec) is False
        assert splitter.likely_a_spec(f"-{spec}") is True
    for s in unambiguous_specs:
        assert splitter.likely_a_spec(s) is True
        assert splitter.likely_a_spec(f"-{s}") is True

    assert splitter.likely_a_spec("-") is True
    assert splitter.likely_a_spec("--") is False

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
            "./pants --check-long-flag --gg -ltrace check --cc test --ii"
            + " src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz",
            dict(
                expected_goals=["check", "test"],
                expected_scope_to_flags={
                    "": ["--gg", "-ltrace"],
                    "check": ["--long-flag", "--cc"],
                    "test": ["--ii"],
                },
                expected_specs=["src/java/org/pantsbuild/foo", "src/java/org/pantsbuild/bar:baz"],
            ),
        ),
        (
            "./pants --fff=arg check --gg-gg=arg-arg test --iii"
            + " --check-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz -ltrace"
            + " --another-global",
            dict(
                expected_goals=["check", "test"],
                expected_scope_to_flags={
                    "": ["--fff=arg", "-ltrace", "--another-global"],
                    "check": ["--gg-gg=arg-arg", "--long-flag"],
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
        goal_split_test("./pants test -", expected_specs=["-"]),
        goal_split_test("./pants test -a/b", expected_specs=["-a/b"]),
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
        "./pants -lerror --fff=arg check --gg-gg=arg-arg test --iii"
        + " --check-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz --"
        + " passthru1 passthru2 -linfo",
        expected_goals=["check", "test"],
        expected_scope_to_flags={
            "": ["-lerror", "--fff=arg"],
            "check": ["--gg-gg=arg-arg", "--long-flag"],
            "test": ["--iii"],
        },
        expected_specs=["src/java/org/pantsbuild/foo", "src/java/org/pantsbuild/bar:baz"],
        expected_passthru=["passthru1", "passthru2", "-linfo"],
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
    return (
        command_line,
        {
            **expected,
            "expected_passthru": None,
            "expected_is_help": True,
        },
    )


def help_no_arguments_test(command_line: str, *scopes: str, **expected):
    return help_test(
        command_line,
        expected_goals=[],
        expected_scope_to_flags={scope: [] for scope in ("", *scopes)},
        expected_specs=[],
        **expected,
    )


@pytest.mark.parametrize(
    "command_line, expected",
    [
        help_no_arguments_test("./pants"),
        help_no_arguments_test("./pants help", "help"),
        help_no_arguments_test("./pants -h", "help"),
        help_no_arguments_test("./pants --help", "help"),
        help_no_arguments_test(
            "./pants help-advanced", "help-advanced", expected_help_advanced=True
        ),
        help_no_arguments_test(
            "./pants --help-advanced", "help-advanced", expected_help_advanced=True
        ),
        help_no_arguments_test("./pants help-all", "help-all", expected_help_all=True),
        help_test(
            "./pants --help-advanced --help",
            expected_goals=["help-advanced"],
            expected_scope_to_flags={"": [], "help": [], "help-advanced": []},
            expected_specs=[],
            expected_help_advanced=False,
        ),
        help_test(
            "./pants --help --help-advanced --builtin-option --help-advanced-option",
            expected_goals=["help"],
            expected_scope_to_flags={
                "": [],
                "help": [],
                "help-advanced": ["--builtin-option", "--option"],
            },
            expected_specs=[],
            expected_help_advanced=True,
        ),
        help_test(
            "./pants -f",
            expected_goals=[],
            expected_scope_to_flags={"": []},
            expected_specs=["-f"],
        ),
        help_test(
            "./pants help check -x",
            expected_goals=["check"],
            expected_scope_to_flags={"": [], "help": [], "check": []},
            expected_specs=["-x"],
        ),
        help_test(
            "./pants check -h",
            expected_goals=["check"],
            expected_scope_to_flags={"": [], "check": [], "help": []},
            expected_specs=[],
        ),
        help_test(
            "./pants -linfo check -h",
            expected_goals=["check"],
            expected_scope_to_flags={"": ["-linfo"], "check": [], "help": []},
            expected_specs=[],
        ),
        help_test(
            "./pants check -h -linfo",
            expected_goals=["check"],
            expected_scope_to_flags={"": ["-linfo"], "check": [], "help": []},
            expected_specs=[],
        ),
        help_test(
            "./pants check --help test",
            expected_goals=["check", "test"],
            expected_scope_to_flags={"": [], "check": [], "help": [], "test": []},
            expected_specs=[],
        ),
        help_test(
            "./pants test src/foo/bar:baz -h",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": [], "help": []},
            expected_specs=["src/foo/bar:baz"],
        ),
        help_test(
            "./pants test src/foo/bar:baz --help",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": [], "help": []},
            expected_specs=["src/foo/bar:baz"],
        ),
        help_test(
            "./pants --help test src/foo/bar:baz",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": [], "help": []},
            expected_specs=["src/foo/bar:baz"],
        ),
        help_test(
            "./pants test --help src/foo/bar:baz",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": [], "help": []},
            expected_specs=["src/foo/bar:baz"],
        ),
        help_test(
            "./pants check --help-advanced test",
            expected_goals=["check", "test"],
            expected_scope_to_flags={"": [], "check": [], "help-advanced": [], "test": []},
            expected_specs=[],
            expected_help_advanced=True,
        ),
        help_test(
            "./pants help-advanced check",
            expected_goals=["check"],
            expected_scope_to_flags={"": [], "check": [], "help-advanced": []},
            expected_specs=[],
            expected_help_advanced=True,
        ),
        help_test(
            "./pants check help-all test --help",
            expected_goals=["check", "test", "help-all"],
            expected_scope_to_flags={"": [], "check": [], "help": [], "help-all": [], "test": []},
            expected_specs=[],
            expected_help_all=False,
        ),
        help_test(
            "./pants bsp --help",
            expected_goals=["bsp"],
            expected_scope_to_flags={"": [], "help": [], "bsp": []},
            expected_specs=[],
        ),
    ],
)
def test_help_detection(splitter: ArgSplitter, command_line: str, expected: dict[str, Any]) -> None:
    assert_valid_split(splitter, command_line, **expected)


def test_version_request_detection(splitter: ArgSplitter) -> None:
    def assert_version_request(args_str: str) -> None:
        split_args = splitter.split_args(shlex.split(args_str))
        assert "version" == split_args.builtin_goal

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


@pytest.mark.parametrize("extra_args", ("", "foo/bar:baz", "f.ext", "-linfo", "--arg"))
def test_no_goal_detection(extra_args: str, splitter: ArgSplitter) -> None:
    split_args = splitter.split_args(shlex.split(f"./pants {extra_args}"))
    assert NO_GOAL_NAME == split_args.builtin_goal


def test_subsystem_scope_is_unknown_goal(splitter: ArgSplitter) -> None:
    assert_unknown_goal(splitter, "./pants jvm reporting", ["jvm", "reporting"])
