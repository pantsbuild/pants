# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from pants.util.contextutil import pushd, temporary_dir


@pytest.fixture
def known_scope_infos() -> list[ScopeInfo]:
    return [
        ScopeInfo(scope, is_goal=True)
        for scope in [
            "compile",
            "compile.java",
            "compile.scala",
            "jvm",
            "jvm.test.junit",
            "reporting",
            "test",
            "test.junit",
        ]
    ] + [ScopeInfo("hidden", is_goal=False)]


@pytest.fixture
def splitter(known_scope_infos) -> ArgSplitter:
    return ArgSplitter(known_scope_infos, buildroot=os.getcwd())


def assert_valid_split(
    splitter: ArgSplitter,
    args_str: str,
    *,
    expected_goals: List[str],
    expected_scope_to_flags: Dict[str, List[str]],
    expected_specs: List[str],
    expected_passthru: Optional[List[str]] = None,
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


def assert_unknown_goal(splitter: ArgSplitter, args_str: str, unknown_goals: List[str]) -> None:
    splitter.split_args(shlex.split(args_str))
    assert isinstance(splitter.help_request, UnknownGoalHelp)
    assert set(unknown_goals) == set(splitter.help_request.unknown_goals)


def test_is_spec(splitter: ArgSplitter, known_scope_infos: list[ScopeInfo]) -> None:
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
    ]

    directories_vs_goals = ["foo", "a_b_c"]
    # TODO: Once we properly ban scopes with dots in them, we can stop testing this case.
    files_vs_dotted_scopes = ["cache.java", "cache.tmp.java"]
    ambiguous_specs = [*directories_vs_goals, *files_vs_dotted_scopes]

    # With no files/directories on disk to tiebreak.
    for spec in ambiguous_specs:
        assert splitter.likely_a_spec(spec) is False
    for s in unambiguous_specs:
        assert splitter.likely_a_spec(s) is True

    # With files/directories on disk to tiebreak.
    with temporary_dir() as tmpdir:
        splitter = ArgSplitter(known_scope_infos, tmpdir)
        for directory in directories_vs_goals:
            Path(tmpdir, directory).mkdir()
        for f in files_vs_dotted_scopes:
            Path(tmpdir, f).touch()
        for spec in ambiguous_specs:
            assert splitter.likely_a_spec(spec) is True


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
            "./pants --compile-java-long-flag -f compile -g compile.java -x test.junit -i "
            "src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz",
            dict(
                expected_goals=["compile", "test"],
                expected_scope_to_flags={
                    "": ["-f"],
                    "compile.java": ["--long-flag", "-x"],
                    "compile": ["-g"],
                    "test.junit": ["-i"],
                },
                expected_specs=["src/java/org/pantsbuild/foo", "src/java/org/pantsbuild/bar:baz"],
            ),
        ),
        (
            "./pants -farg --fff=arg compile --gg-gg=arg-arg -g test.junit --iii "
            "--compile-java-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz",
            dict(
                expected_goals=["compile", "test"],
                expected_scope_to_flags={
                    "": ["-farg", "--fff=arg"],
                    "compile": ["--gg-gg=arg-arg", "-g"],
                    "test.junit": ["--iii"],
                    "compile.java": ["--long-flag"],
                },
                expected_specs=["src/java/org/pantsbuild/foo", "src/java/org/pantsbuild/bar:baz"],
            ),
        ),
        # Distinguish goals from specs.
        (
            "./pants compile test foo::",
            dict(
                expected_goals=["compile", "test"],
                expected_scope_to_flags={"": [], "compile": [], "test": []},
                expected_specs=["foo::"],
            ),
        ),
        (
            "./pants compile test foo::",
            dict(
                expected_goals=["compile", "test"],
                expected_scope_to_flags={"": [], "compile": [], "test": []},
                expected_specs=["foo::"],
            ),
        ),
        (
            "./pants compile test:test",
            dict(
                expected_goals=["compile"],
                expected_scope_to_flags={"": [], "compile": []},
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
            # An argument that looks like a file, but is a known scope, should be interpreted as a goal.
            "./pants test compile.java",
            dict(
                expected_goals=["test", "compile"],
                expected_scope_to_flags={"": [], "test": [], "compile.java": []},
                expected_specs=[],
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


def test_unknwon_goal_is_not_file(splitter: ArgSplitter) -> None:
    # An argument that looks like a file, and is not a known scope nor exists on the file system,
    # should be interpreted as an unknown goal.
    assert_unknown_goal(splitter, "./pants test compile.haskell", ["compile.haskell"])


def test_unknown_goal_is_file(splitter: ArgSplitter) -> None:
    # An argument that looks like a file, and is not a known scope but _does_ exist on the file
    # system, should be interpreted as a spec.
    with temporary_dir() as tmpdir, pushd(tmpdir):
        Path(tmpdir, "compile.haskell").touch()
        splitter._buildroot = Path(tmpdir)
        assert_valid_split(
            splitter,
            "./pants test compile.haskell",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": []},
            expected_specs=["compile.haskell"],
        )


def test_descoping_qualified_flags(splitter: ArgSplitter) -> None:
    assert_valid_split(
        splitter,
        "./pants compile test --compile-java-bar --no-test-junit-baz foo/bar",
        expected_goals=["compile", "test"],
        expected_scope_to_flags={
            "": [],
            "compile": [],
            "compile.java": ["--bar"],
            "test": [],
            "test.junit": ["--no-baz"],
        },
        expected_specs=["foo/bar"],
    )
    # Qualified flags don't count as explicit goals.
    assert_valid_split(
        splitter,
        "./pants compile --test-junit-bar foo/bar",
        expected_goals=["compile"],
        expected_scope_to_flags={"": [], "compile": [], "test.junit": ["--bar"]},
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
        "./pants -farg --fff=arg compile --gg-gg=arg-arg -g test.junit --iii "
        "--compile-java-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz -- "
        "passthru1 passthru2",
        expected_goals=["compile", "test"],
        expected_scope_to_flags={
            "": ["-farg", "--fff=arg"],
            "compile": ["--gg-gg=arg-arg", "-g"],
            "compile.java": ["--long-flag"],
            "test.junit": ["--iii"],
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
    # Qualified task subsystem flag in global scope.
    assert_valid_split(
        splitter,
        "./pants --jvm-test-junit-options=-Dbar=baz test foo:bar",
        expected_goals=["test"],
        expected_scope_to_flags={"": [], "jvm.test.junit": ["--options=-Dbar=baz"], "test": []},
        expected_specs=["foo:bar"],
    )
    # Unqualified task subsystem flag in task scope.
    # Note that this exposes a small problem: You can't set an option on the cmd-line if that
    # option's name begins with any subsystem scope. For example, if test.junit has some option
    # named --jvm-foo, then it cannot be set on the cmd-line, because the ArgSplitter will assume
    # it's an option --foo on the jvm subsystem.
    assert_valid_split(
        splitter,
        "./pants test.junit --jvm-options=-Dbar=baz foo:bar",
        expected_goals=["test"],
        expected_scope_to_flags={
            "": [],
            "jvm.test.junit": ["--options=-Dbar=baz"],
            "test.junit": [],
        },
        expected_specs=["foo:bar"],
    )
    # Global-only flag in task scope.
    assert_valid_split(
        splitter,
        "./pants test.junit --reporting-template-dir=path foo:bar",
        expected_goals=["test"],
        expected_scope_to_flags={
            "": [],
            "reporting": ["--template-dir=path"],
            "test.junit": [],
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
            "./pants help compile -x",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": ["-x"]},
            expected_specs=[],
        ),
        help_test(
            "./pants help compile -x",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": ["-x"]},
            expected_specs=[],
        ),
        help_test(
            "./pants compile -h",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": []},
            expected_specs=[],
        ),
        help_test(
            "./pants compile --help test",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={"": [], "compile": [], "test": []},
            expected_specs=[],
        ),
        help_test(
            "./pants test src/foo/bar:baz -h",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": []},
            expected_specs=["src/foo/bar:baz"],
        ),
        help_test(
            "./pants compile --help-advanced test",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={"": [], "compile": [], "test": []},
            expected_specs=[],
            expected_help_advanced=True,
        ),
        help_test(
            "./pants help-advanced compile",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": []},
            expected_specs=[],
            expected_help_advanced=True,
        ),
        help_test(
            "./pants compile help-all test --help",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={"": [], "compile": [], "test": []},
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
    # A version request supercedes anything else.
    assert_version_request("./pants --version compile --foo --bar path/to/target")


@pytest.mark.parametrize(
    "command_line, unknown_goals",
    [
        ("./pants foo", ["foo"]),
        ("./pants compile foo", ["foo"]),
        ("./pants foo bar baz:qux", ["foo", "bar"]),
        ("./pants foo compile bar baz:qux", ["foo", "bar"]),
    ],
)
def test_unknown_goal_detection(
    splitter: ArgSplitter, command_line: str, unknown_goals: list[str]
) -> None:
    assert_unknown_goal(splitter, command_line, unknown_goals)


def test_no_goal_detection(splitter: ArgSplitter) -> None:
    splitter.split_args(shlex.split("./pants foo/bar:baz"))
    assert isinstance(splitter.help_request, NoGoalHelp)


def test_hidden_scope_is_unknown_goal(splitter: ArgSplitter) -> None:
    assert_unknown_goal(splitter, "./pants hidden", ["hidden"])
