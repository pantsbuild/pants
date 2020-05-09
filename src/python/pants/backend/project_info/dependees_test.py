# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List

from pants.backend.project_info.dependees import Dependees
from pants.backend.project_info.dependees import DependeesOutputFormat as OutputFormat
from pants.backend.project_info.dependees import dependees_goal
from pants.engine.target import Dependencies, Target
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class MockTarget(Target):
    alias = "tgt"
    core_fields = (Dependencies,)


class DependeesTest(GoalRuleTestBase):
    goal_cls = Dependees

    @classmethod
    def target_types(cls):
        return [MockTarget]

    @classmethod
    def rules(cls):
        return (*super().rules(), dependees_goal)

    def setUp(self) -> None:
        self.add_to_build_file("base", "tgt()")
        self.add_to_build_file("intermediate", "tgt(dependencies=['base'])")
        self.add_to_build_file("leaf", "tgt(dependencies=['intermediate'])")

    def assert_dependees(
        self,
        *,
        targets: List[str],
        expected: List[str],
        transitive: bool = False,
        closed: bool = False,
        output_format: OutputFormat = OutputFormat.text,
    ) -> None:
        args = [f"--output-format={output_format.value}"]
        if transitive:
            args.append("--transitive")
        if closed:
            args.append("--closed")
        self.assert_console_output_ordered(
            *expected,
            args=[*args, *targets],
            global_args=["--backend-packages2=pants.backend.project_info"],
        )

    def test_no_targets(self) -> None:
        self.assert_dependees(targets=[], expected=[])
        self.assert_dependees(targets=[], output_format=OutputFormat.json, expected=["{}"])

    def test_normal(self) -> None:
        self.assert_dependees(targets=["base:base"], expected=["intermediate:intermediate"])
        self.assert_dependees(
            targets=["base:base"],
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "base:base": [
                        "intermediate:intermediate"
                    ]
                }"""
            ).splitlines(),
        )

    def test_no_dependees(self) -> None:
        self.assert_dependees(targets=["leaf:leaf"], expected=[])
        self.assert_dependees(
            targets=["leaf:leaf"],
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "leaf:leaf": []
                }"""
            ).splitlines(),
        )

    def test_closed(self) -> None:
        self.assert_dependees(targets=["leaf:leaf"], closed=True, expected=["leaf:leaf"])
        self.assert_dependees(
            targets=["leaf:leaf"],
            closed=True,
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "leaf:leaf": [
                        "leaf:leaf"
                    ]
                }"""
            ).splitlines(),
        )

    def test_transitive(self) -> None:
        self.assert_dependees(
            targets=["base:base"],
            transitive=True,
            expected=["intermediate:intermediate", "leaf:leaf"],
        )
        self.assert_dependees(
            targets=["base:base"],
            transitive=True,
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "base:base": [
                        "intermediate:intermediate",
                        "leaf:leaf"
                    ]
                }"""
            ).splitlines(),
        )

    def test_multiple_specified_targets(self) -> None:
        # This tests that --output-format=text will deduplicate and that --output-format=json will
        # preserve which dependee belongs to which specified target.
        self.assert_dependees(
            targets=["base:base", "intermediate:intermediate"],
            transitive=True,
            # NB: `intermediate` is not included because it's a root and we have `--no-closed`.
            expected=["leaf:leaf"],
        )
        self.assert_dependees(
            targets=["base:base", "intermediate:intermediate"],
            transitive=True,
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "base:base": [
                        "intermediate:intermediate",
                        "leaf:leaf"
                    ],
                    "intermediate:intermediate": [
                        "leaf:leaf"
                    ]
                }"""
            ).splitlines(),
        )
