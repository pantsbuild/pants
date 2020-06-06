# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import shlex
import unittest
from functools import partial
from pathlib import Path
from typing import Dict, List, Optional

from pants.option.arg_splitter import (
    ArgSplitter,
    NoGoalHelp,
    OptionsHelp,
    UnknownGoalHelp,
    VersionHelp,
)
from pants.option.scope import ScopeInfo
from pants.util.contextutil import pushd, temporary_dir


def task(scope: str) -> ScopeInfo:
    return ScopeInfo(scope, ScopeInfo.TASK)


def intermediate(scope: str) -> ScopeInfo:
    return ScopeInfo(scope, ScopeInfo.INTERMEDIATE)


def subsys(scope: str) -> ScopeInfo:
    return ScopeInfo(scope, ScopeInfo.SUBSYSTEM)


class ArgSplitterTest(unittest.TestCase):
    _known_scope_infos = [
        intermediate("compile"),
        task("compile.java"),
        task("compile.scala"),
        subsys("jvm"),
        subsys("jvm.test.junit"),
        subsys("reporting"),
        intermediate("test"),
        task("test.junit"),
    ]

    def assert_valid_split(
        self,
        args_str: str,
        *,
        expected_goals: List[str],
        expected_scope_to_flags: Dict[str, List[str]],
        expected_specs: List[str],
        expected_passthru: Optional[List[str]] = None,
        expected_is_help: bool = False,
        expected_help_advanced: bool = False,
        expected_help_all: bool = False,
        expected_unknown_scopes: Optional[List[str]] = None
    ) -> None:
        expected_passthru = expected_passthru or []
        expected_unknown_scopes = expected_unknown_scopes or []
        splitter = ArgSplitter(ArgSplitterTest._known_scope_infos)
        args = shlex.split(args_str)
        split_args = splitter.split_args(args)
        assert expected_goals == split_args.goals
        assert expected_scope_to_flags == split_args.scope_to_flags
        assert expected_specs == split_args.specs
        assert expected_passthru == split_args.passthru
        assert expected_is_help == (splitter.help_request is not None)
        assert expected_help_advanced == (
            isinstance(splitter.help_request, OptionsHelp) and splitter.help_request.advanced
        )
        assert expected_help_all == (
            isinstance(splitter.help_request, OptionsHelp) and splitter.help_request.all_scopes
        )
        assert expected_unknown_scopes == split_args.unknown_scopes

    def assert_unknown_goal(self, args_str: str, unknown_goals: List[str]) -> None:
        splitter = ArgSplitter(ArgSplitterTest._known_scope_infos)
        result = splitter.split_args(shlex.split(args_str))
        assert isinstance(splitter.help_request, UnknownGoalHelp)
        assert set(unknown_goals) == set(splitter.help_request.unknown_goals)
        assert result.unknown_scopes == unknown_goals

    def test_is_spec(self) -> None:
        def assert_spec(arg: str) -> None:
            assert ArgSplitter.likely_a_spec(arg) is True

        def assert_not_spec(arg: str) -> None:
            assert ArgSplitter.likely_a_spec(arg) is False

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
            "!/a/b",
            "!/a/b.txt",
        ]
        for s in unambiguous_specs:
            assert_spec(s)

        directories_vs_goals = ["foo", "a_b_c"]
        files_vs_subscopes = ["cache.java", "cache.tmp.java"]
        ambiguous_specs = [*directories_vs_goals, *files_vs_subscopes]
        for spec in ambiguous_specs:
            assert_not_spec(spec)
        with temporary_dir() as tmpdir, pushd(tmpdir):
            for dir in directories_vs_goals:
                Path(tmpdir, dir).mkdir()
            for f in files_vs_subscopes:
                Path(tmpdir, f).touch()
            for spec in ambiguous_specs:
                assert_spec(spec)

    def test_basic_arg_splitting(self) -> None:
        # Various flag combos.
        self.assert_valid_split(
            "./pants --compile-java-long-flag -f compile -g compile.java -x test.junit -i "
            "src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={
                "": ["-f"],
                "compile.java": ["--long-flag", "-x"],
                "compile": ["-g"],
                "test.junit": ["-i"],
            },
            expected_specs=["src/java/org/pantsbuild/foo", "src/java/org/pantsbuild/bar:baz"],
        )
        self.assert_valid_split(
            "./pants -farg --fff=arg compile --gg-gg=arg-arg -g test.junit --iii "
            "--compile-java-long-flag src/java/org/pantsbuild/foo src/java/org/pantsbuild/bar:baz",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={
                "": ["-farg", "--fff=arg"],
                "compile": ["--gg-gg=arg-arg", "-g"],
                "test.junit": ["--iii"],
                "compile.java": ["--long-flag"],
            },
            expected_specs=["src/java/org/pantsbuild/foo", "src/java/org/pantsbuild/bar:baz"],
        )

    def test_distinguish_goals_from_specs(self) -> None:
        self.assert_valid_split(
            "./pants compile test foo::",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={"": [], "compile": [], "test": []},
            expected_specs=["foo::"],
        )
        self.assert_valid_split(
            "./pants compile test foo::",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={"": [], "compile": [], "test": []},
            expected_specs=["foo::"],
        )
        self.assert_valid_split(
            "./pants compile test:test",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": []},
            expected_specs=["test:test"],
        )

        assert_test_goal_split = partial(
            self.assert_valid_split,
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": []},
        )
        assert_test_goal_split("./pants test test:test", expected_specs=["test:test"])
        assert_test_goal_split("./pants test ./test", expected_specs=["./test"])
        assert_test_goal_split("./pants test //test", expected_specs=["//test"])
        assert_test_goal_split("./pants test ./test.txt", expected_specs=["./test.txt"])
        assert_test_goal_split("./pants test test/test.txt", expected_specs=["test/test.txt"])
        assert_test_goal_split("./pants test test/test", expected_specs=["test/test"])
        assert_test_goal_split("./pants test .", expected_specs=["."])
        assert_test_goal_split("./pants test *", expected_specs=["*"])
        assert_test_goal_split("./pants test test/*.txt", expected_specs=["test/*.txt"])
        assert_test_goal_split("./pants test test/**/*", expected_specs=["test/**/*"])
        assert_test_goal_split("./pants test !", expected_specs=["!"])
        assert_test_goal_split("./pants test !a/b", expected_specs=["!a/b"])

        # An argument that looks like a file, but is a known scope, should be interpreted as a goal.
        self.assert_valid_split(
            "./pants test compile.java",
            expected_goals=["test", "compile"],
            expected_scope_to_flags={"": [], "test": [], "compile.java": []},
            expected_specs=[],
        )
        # An argument that looks like a file, and is not a known scope nor exists on the file system,
        # should be interpreted as an unknown goal.
        self.assert_unknown_goal("./pants test compile.haskell", ["compile.haskell"])
        # An argument that looks like a file, and is not a known scope but _does_ exist on the file
        # system, should be interpreted as a spec.
        with temporary_dir() as tmpdir, pushd(tmpdir):
            Path(tmpdir, "compile.haskell").touch()
            self.assert_valid_split(
                "./pants test compile.haskell",
                expected_goals=["test"],
                expected_scope_to_flags={"": [], "test": []},
                expected_specs=["compile.haskell"],
            )

    def test_descoping_qualified_flags(self) -> None:
        self.assert_valid_split(
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
        self.assert_valid_split(
            "./pants compile --test-junit-bar foo/bar",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": [], "test.junit": ["--bar"]},
            expected_specs=["foo/bar"],
        )

    def test_passthru_args(self) -> None:
        self.assert_valid_split(
            "./pants test foo/bar -- -t arg",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": []},
            expected_specs=["foo/bar"],
            expected_passthru=["-t", "arg"],
        )
        self.assert_valid_split(
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

    def test_subsystem_flags(self) -> None:
        # Global subsystem flag in global scope.
        self.assert_valid_split(
            "./pants --jvm-options=-Dbar=baz test foo:bar",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "jvm": ["--options=-Dbar=baz"], "test": []},
            expected_specs=["foo:bar"],
        )
        # Qualified task subsystem flag in global scope.
        self.assert_valid_split(
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
        self.assert_valid_split(
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
        self.assert_valid_split(
            "./pants test.junit --reporting-template-dir=path foo:bar",
            expected_goals=["test"],
            expected_scope_to_flags={
                "": [],
                "reporting": ["--template-dir=path"],
                "test.junit": [],
            },
            expected_specs=["foo:bar"],
        )

    def test_help_detection(self) -> None:
        assert_help = partial(
            self.assert_valid_split, expected_passthru=None, expected_is_help=True,
        )
        assert_help_no_arguments = partial(
            assert_help, expected_goals=[], expected_scope_to_flags={"": []}, expected_specs=[],
        )
        assert_help_no_arguments("./pants")
        assert_help_no_arguments("./pants help")
        assert_help_no_arguments("./pants -h")
        assert_help_no_arguments("./pants --help")
        assert_help_no_arguments("./pants help-advanced", expected_help_advanced=True)
        assert_help_no_arguments("./pants help --help-advanced", expected_help_advanced=True)
        assert_help_no_arguments("./pants --help-advanced", expected_help_advanced=True)
        assert_help_no_arguments("./pants --help --help-advanced", expected_help_advanced=True)
        assert_help_no_arguments("./pants --help-advanced --help", expected_help_advanced=True)
        assert_help_no_arguments("./pants help-all", expected_help_all=True)
        assert_help_no_arguments("./pants --help-all", expected_help_all=True)
        assert_help_no_arguments("./pants --help --help-all", expected_help_all=True)
        assert_help_no_arguments(
            "./pants help-advanced --help-all", expected_help_advanced=True, expected_help_all=True,
        )
        assert_help_no_arguments(
            "./pants --help-all --help --help-advanced",
            expected_help_advanced=True,
            expected_help_all=True,
        )

        assert_help(
            "./pants -f",
            expected_goals=[],
            expected_scope_to_flags={"": ["-f"]},
            expected_specs=[],
        )
        assert_help(
            "./pants help compile -x",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": ["-x"]},
            expected_specs=[],
        )
        assert_help(
            "./pants help compile -x",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": ["-x"]},
            expected_specs=[],
        )
        assert_help(
            "./pants compile -h",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": []},
            expected_specs=[],
        )
        assert_help(
            "./pants compile --help test",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={"": [], "compile": [], "test": []},
            expected_specs=[],
        )
        assert_help(
            "./pants test src/foo/bar:baz -h",
            expected_goals=["test"],
            expected_scope_to_flags={"": [], "test": []},
            expected_specs=["src/foo/bar:baz"],
        )

        assert_help(
            "./pants compile --help-advanced test",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={"": [], "compile": [], "test": []},
            expected_specs=[],
            expected_help_advanced=True,
        )
        assert_help(
            "./pants help-advanced compile",
            expected_goals=["compile"],
            expected_scope_to_flags={"": [], "compile": []},
            expected_specs=[],
            expected_help_advanced=True,
        )
        assert_help(
            "./pants compile help-all test --help",
            expected_goals=["compile", "test"],
            expected_scope_to_flags={"": [], "compile": [], "test": []},
            expected_specs=[],
            expected_help_all=True,
        )

    def test_version_request_detection(self) -> None:
        def assert_version_request(args_str: str) -> None:
            splitter = ArgSplitter(ArgSplitterTest._known_scope_infos)
            splitter.split_args(shlex.split(args_str))
            self.assertTrue(isinstance(splitter.help_request, VersionHelp))

        assert_version_request("./pants -v")
        assert_version_request("./pants -V")
        assert_version_request("./pants --version")
        # A version request supercedes anything else.
        assert_version_request("./pants --version compile --foo --bar path/to/target")

    def test_unknown_goal_detection(self) -> None:
        self.assert_unknown_goal("./pants foo", ["foo"])
        self.assert_unknown_goal("./pants compile foo", ["foo"])
        self.assert_unknown_goal("./pants foo bar baz:qux", ["foo", "bar"])
        self.assert_unknown_goal("./pants foo compile bar baz:qux", ["foo", "bar"])

    def test_no_goal_detection(self) -> None:
        splitter = ArgSplitter(ArgSplitterTest._known_scope_infos)
        splitter.split_args(shlex.split("./pants foo/bar:baz"))
        self.assertTrue(isinstance(splitter.help_request, NoGoalHelp))
