# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.project_info import peek
from pants.backend.project_info.peek import Peek
from pants.core.target_types import Files
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=peek.rules(), target_types=[Files])


def test_example(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file("project", "# A comment\nfiles(sources=[])")
    result = rule_runner.run_goal_rule(Peek, args=["project"])
    assert result.stdout == dedent(
        """\
        -------------
        project/BUILD
        -------------
        # A comment
        files(sources=[])

        """
    )
