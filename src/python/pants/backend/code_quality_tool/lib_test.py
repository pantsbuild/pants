# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent  # noqa: PNT20

from pants.backend.code_quality_tool.lib import CodeQualityToolConfig, build_rules, CodeQualityToolTarget
from pants.backend.project_info.list_targets import List, rules as list_rules
from pants.backend.python.target_types import PythonRequirementTarget
from pants.core.goals.fmt import Fmt
from pants.core.goals.lint import Lint
from pants.core.target_types import FileTarget
from pants.testutil.rule_runner import RuleRunner

from pants.core.register import rules as core_rules
from pants.core.util_rules import source_files, adhoc_process_support
from pants.engine import process
from pants.backend.python import register as register_python


def test_lint_built_rule():
    cfg = CodeQualityToolConfig(
        goal='lint',
        target='//:flake8_tool',
        name='Flake8',
        scope='flake8_tool'
    )

    code_quality_tool_rules = build_rules(cfg)

    rule_runner = RuleRunner(
        target_types=[CodeQualityToolTarget, PythonRequirementTarget, FileTarget],
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
            
            file(
                name="flake8_conf",
                source=".flake8"
            )
            
            code_quality_tool(
                name="flake8_tool",
                runnable=":flake8",
                execution_dependencies=[":flake8_conf"],
                file_glob_include=["**/*.py"],
                file_glob_exclude=["messy_ignored_dir/**"],
            )
            """
        ),
        "good_fmt.py": "foo = 5\n",
        "unused_import_saved_by_conf.py": "import os\n",
        "messy_ignored_dir/messy_file.py": "ignoreme=10",
        "not_a_dot_py_file.nopy": "notpy=100",
        ".flake8": dedent(
            """
            [flake8]
            extend-ignore = F401
            """),
    })

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 0
    assert "flake8_tool succeeded" in res.stderr

    res = rule_runner.run_goal_rule(Lint, args=["good_fmt.py"])
    assert res.exit_code == 0
    assert "flake8_tool succeeded" in res.stderr

    rule_runner.write_files({
        "bad_fmt.py": "baz=5\n"
    })

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 1
    assert "flake8_tool failed" in res.stderr

    res = rule_runner.run_goal_rule(Lint, args=["bad_fmt.py"])
    assert res.exit_code == 1
    assert "flake8_tool failed" in res.stderr

    res = rule_runner.run_goal_rule(Lint, args=["good_fmt.py"])
    assert res.exit_code == 0
    assert "flake8_tool succeeded" in res.stderr


def test_fmt_built_rule():
    cfg = CodeQualityToolConfig(
        goal='fmt',
        target='//:black_tool',
        name='Black',
        scope='black_formatter'
    )

    code_quality_tool_rules = build_rules(cfg)

    rule_runner = RuleRunner(
        target_types=[CodeQualityToolTarget, PythonRequirementTarget, FileTarget],
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
                name="black",
                requirements=["black==22.6.0"]
            )

            code_quality_tool(
                name="black_tool",
                runnable=":black",
                runnable_dependencies=[],
                file_glob_include=["**/*.py"],
            )
            """
        ),
        "good_fmt.py": "foo = 5\n",
        "needs_repair.py": "bar=10\n",
    })

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 1
    assert "black_formatter failed" in res.stderr

    res = rule_runner.run_goal_rule(Fmt, args=["::"])
    assert res.exit_code == 0
    assert "black_formatter made changes" in res.stderr

    assert "bar = 10\n" == rule_runner.read_file("needs_repair.py")

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 0
    assert "black_formatter succeeded" in res.stderr
