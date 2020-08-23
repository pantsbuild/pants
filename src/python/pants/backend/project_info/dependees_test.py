# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List

from pants.backend.project_info.dependees import DependeesGoal
from pants.backend.project_info.dependees import DependeesOutputFormat as OutputFormat
from pants.backend.project_info.dependees import rules as dependee_rules
from pants.engine.target import Dependencies, Target
from pants.testutil.test_base import TestBase


class MockTarget(Target):
    alias = "tgt"
    core_fields = (Dependencies,)


class DependeesTest(TestBase):
    @classmethod
    def target_types(cls):
        return [MockTarget]

    @classmethod
    def rules(cls):
        return (*super().rules(), *dependee_rules())

    def setUp(self) -> None:
        super().setUp()
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
        result = self.run_goal_rule(DependeesGoal, args=[*args, *targets])
        assert result.stdout.splitlines() == expected

    def test_no_targets(self) -> None:
        self.assert_dependees(targets=[], expected=[])
        self.assert_dependees(targets=[], output_format=OutputFormat.json, expected=["{}"])

    def test_normal(self) -> None:
        self.assert_dependees(targets=["base"], expected=["intermediate"])
        self.assert_dependees(
            targets=["base"],
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "base": [
                        "intermediate"
                    ]
                }"""
            ).splitlines(),
        )

    def test_no_dependees(self) -> None:
        self.assert_dependees(targets=["leaf"], expected=[])
        self.assert_dependees(
            targets=["leaf"],
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "leaf": []
                }"""
            ).splitlines(),
        )

    def test_closed(self) -> None:
        self.assert_dependees(targets=["leaf"], closed=True, expected=["leaf"])
        self.assert_dependees(
            targets=["leaf"],
            closed=True,
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "leaf": [
                        "leaf"
                    ]
                }"""
            ).splitlines(),
        )

    def test_transitive(self) -> None:
        self.assert_dependees(
            targets=["base"], transitive=True, expected=["intermediate", "leaf"],
        )
        self.assert_dependees(
            targets=["base"],
            transitive=True,
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "base": [
                        "intermediate",
                        "leaf"
                    ]
                }"""
            ).splitlines(),
        )

    def test_multiple_specified_targets(self) -> None:
        # This tests that --output-format=text will deduplicate and that --output-format=json will
        # preserve which dependee belongs to which specified target.
        self.assert_dependees(
            targets=["base", "intermediate"],
            transitive=True,
            # NB: `intermediate` is not included because it's a root and we have `--no-closed`.
            expected=["leaf"],
        )
        self.assert_dependees(
            targets=["base", "intermediate"],
            transitive=True,
            output_format=OutputFormat.json,
            expected=dedent(
                """\
                {
                    "base": [
                        "intermediate",
                        "leaf"
                    ],
                    "intermediate": [
                        "leaf"
                    ]
                }"""
            ).splitlines(),
        )
