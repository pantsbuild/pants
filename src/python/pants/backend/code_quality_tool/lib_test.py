# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent  # noqa: PNT20

from pants.backend.code_quality_tool.lib import CodeQualityToolConfig, build_rules, CodeQualityToolTarget
from pants.backend.project_info.list_targets import List, rules as list_rules
from pants.backend.python.target_types import PythonRequirementTarget
from pants.core.goals.lint import Lint
from pants.testutil.rule_runner import RuleRunner

from pants.core.register import rules as core_rules
from pants.core.util_rules import source_files, adhoc_process_support
from pants.engine import process
from pants.backend.python import register as register_python


def test_builds_rules():
    cfg = CodeQualityToolConfig(
        goal='lint',
        target='//:flake8_tool',
        name='Flake8',
        scope='flake8_tool'
    )

    code_quality_tool_rules = build_rules(cfg)

    rule_runner = RuleRunner(
        target_types=[CodeQualityToolTarget, PythonRequirementTarget],
        rules=[
            *source_files.rules(),
            *core_rules(),
            *process.rules(),
            *list_rules(),
            *adhoc_process_support.rules(),
            *register_python.rules(),
            *code_quality_tool_rules,
        ],
        preserve_tmpdirs=True,
    )

    rule_runner.write_files({
        "BUILD": dedent(
            """
            python_requirement(
                name="flake8",
                requirements=["flake8==5.0.4"]
            )
            
            code_quality_tool(
                name="flake8_tool",
                runnable=":flake8",
                runnable_dependencies=[],
                file_glob_include=["**/*.py"],
                file_glob_exclude=["pants-plugins/**"],
            )
            """
        ),
        "good_fmt.py": dedent(
            """
            foo = 5
            """
        ),
        "bad_fmt.py": dedent(
            """
            bar=5
            """
        ),
    })

    list_result = rule_runner.run_goal_rule(
        List, args=["::"]
    )

    assert list_result.exit_code == 0
    assert list(sorted(list_result.stdout.splitlines())) == [
        "//:flake8",
        "//:flake8_tool",
    ]

    good_file_lint_result = rule_runner.run_goal_rule(
        Lint, args=["good_fmt.py"]
    )

    assert good_file_lint_result.exit_code == 0
    assert "flake8_tool succeeded" in good_file_lint_result.stderr

    bad_file_lint_result = rule_runner.run_goal_rule(
        Lint, args=["bad_fmt.py"]
    )
    assert bad_file_lint_result.exit_code == 1
    assert "flake8_tool failed" in bad_file_lint_result.stderr
