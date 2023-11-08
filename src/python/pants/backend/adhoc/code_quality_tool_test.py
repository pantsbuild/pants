# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent  # noqa: PNT20

import pytest

from pants.backend.adhoc.code_quality_tool import (
    CodeQualityToolRuleBuilder,
    CodeQualityToolTarget,
    CodeQualityToolUnsupportedGoalError,
    base_rules,
)
from pants.backend.python import register as register_python
from pants.backend.python.target_types import PythonRequirementTarget, PythonSourceTarget
from pants.core.goals.fix import Fix
from pants.core.goals.fmt import Fmt
from pants.core.goals.lint import Lint
from pants.core.register import rules as core_rules
from pants.core.target_types import FileTarget
from pants.core.util_rules import source_files
from pants.engine import process
from pants.testutil.rule_runner import RuleRunner


def test_error_on_unrecognized_goal():
    with pytest.raises(CodeQualityToolUnsupportedGoalError):
        CodeQualityToolRuleBuilder(
            goal="package", target="build-support:flake8_tool", name="Flake8", scope="flake8_tool"
        )


def make_rule_runner(*cfgs: CodeQualityToolRuleBuilder):
    rules = [
        *source_files.rules(),
        *core_rules(),
        *process.rules(),
        *register_python.rules(),
        *base_rules(),
    ]
    for cfg in cfgs:
        rules.extend(cfg.rules())

    return RuleRunner(
        target_types=[
            CodeQualityToolTarget,
            PythonRequirementTarget,
            FileTarget,
            PythonSourceTarget,
        ],
        rules=rules,
    )


def test_lint_tool():
    cfg = CodeQualityToolRuleBuilder(
        goal="lint", target="build-support:no_badcode_tool", name="No Bad Code", scope="nobadcode"
    )

    rule_runner = make_rule_runner(cfg)

    # Implements a linter with a python script that detects the presence
    # of a configurable list of problem strings in the files to be linted.
    rule_runner.write_files(
        {
            "build-support/BUILD": dedent(
                """
            python_source(
                name="no_badcode",
                source="no_badcode.py",
            )

            code_quality_tool(
                name="no_badcode_tool",
                runnable=":no_badcode",
                execution_dependencies=[":badcode_conf"],
                file_glob_include=["**/*.py"],
                file_glob_exclude=["messy_ignored_dir/**", "build-support/**"],
                args=["build-support/badcode.conf"],
            )

            file(
                name="badcode_conf",
                source="badcode.conf"
            )
            """
            ),
            "build-support/no_badcode.py": dedent(
                """
            import sys

            if __name__ == '__main__':
                config_file = sys.argv[1]
                with open(config_file) as cfgfile:
                    badcode_strings = cfgfile.read().strip().split(",")

                source_files = sys.argv[2:]
                failed = False
                for fpath in source_files:
                    with open(fpath) as f:
                        for i, line in enumerate(f):
                            for badcode_string in badcode_strings:
                                if badcode_string in line:
                                    print(f"{fpath}:{i + 1} found {badcode_string}")
                                    failed = True
                if failed:
                    sys.exit(1)
            """
            ),
            "build-support/badcode.conf": "badcode,brokencode,sillycode",
            "good_file.py": "okcode = 5",
            "messy_ignored_dir/messy_file.py": "brokencode = 10",
            "not_a_dot_py_file.md": "This is sillycode",
        }
    )

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 0
    assert "nobadcode succeeded" in res.stderr

    res = rule_runner.run_goal_rule(Lint, args=["good_file.py"])
    assert res.exit_code == 0
    assert "nobadcode succeeded" in res.stderr

    rule_runner.write_files({"bad_file.py": "brokencode = 5\n"})

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 1
    assert "nobadcode failed" in res.stderr

    res = rule_runner.run_goal_rule(Lint, args=["bad_file.py"])
    assert res.exit_code == 1
    assert "nobadcode failed" in res.stderr

    res = rule_runner.run_goal_rule(Lint, args=["good_file.py"])
    assert res.exit_code == 0
    assert "nobadcode succeeded" in res.stderr


def test_fix_built_rule():
    cfg = CodeQualityToolRuleBuilder(
        goal="fix", target="//:black_tool", name="Black", scope="black_fixer"
    )

    rule_runner = make_rule_runner(cfg)

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
            python_requirement(
                name="black",
                requirements=["black==22.6.0"]
            )

            code_quality_tool(
                name="black_tool",
                runnable=":black",
                file_glob_include=["**/*.py"],
            )
            """
            ),
            "good_fmt.py": "foo = 5\n",
            "needs_repair.py": "bar=10\n",
        }
    )

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 1
    assert "black_fixer failed" in res.stderr

    res = rule_runner.run_goal_rule(Fix, args=["::"])
    assert res.exit_code == 0
    assert "black_fixer made changes" in res.stderr

    assert "bar = 10\n" == rule_runner.read_file("needs_repair.py")

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 0
    assert "black_fixer succeeded" in res.stderr


def test_several_formatters():
    black_cfg = CodeQualityToolRuleBuilder(
        goal="fmt", target="//:black_tool", name="Black", scope="black_formatter"
    )

    isort_cfg = CodeQualityToolRuleBuilder(
        goal="fmt", target="//:isort_tool", name="isort", scope="isort_formatter"
    )

    rule_runner = make_rule_runner(black_cfg, isort_cfg)

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
            python_requirement(
                name="black",
                requirements=["black==22.6.0"]
            )

            python_requirement(
                name="isort",
                requirements=["isort==5.9.3"]
            )

            code_quality_tool(
                name="black_tool",
                runnable=":black",
                file_glob_include=["**/*.py"],
            )

            code_quality_tool(
                name="isort_tool",
                runnable=":isort",
                file_glob_include=["**/*.py"],
            )
            """
            ),
            # the import order will be fixed by isort
            # the spacing on the foo line will be fixed by black
            "needs_repair.py": dedent(
                """
            import b
            import a

            foo=a.a+b.b
            """
            ).lstrip(),
        }
    )

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 1
    assert "isort_formatter failed" in res.stderr
    assert "black_formatter failed" in res.stderr

    res = rule_runner.run_goal_rule(Fmt, args=["::"])
    assert res.exit_code == 0
    assert "isort_formatter made changes" in res.stderr
    assert "black_formatter made changes" in res.stderr

    assert (
        dedent(
            """
        import a
        import b

        foo = a.a + b.b
        """
        ).lstrip()
        == rule_runner.read_file("needs_repair.py")
    )

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 0
    assert "isort_formatter succeeded" in res.stderr
    assert "black_formatter succeeded" in res.stderr

    rule_runner.write_files(
        {
            "only_fix_imports.py": dedent(
                """
            import b
            import a

            bar=a.a+b.b
            """
            ).lstrip(),
        }
    )
    res = rule_runner.run_goal_rule(Fmt, args=["--only=isort_formatter", "only_fix_imports.py"])
    assert res.exit_code == 0
    assert "isort_formatter made changes" in res.stderr
    assert "black" not in res.stderr
    assert (
        dedent(
            """
        import a
        import b

        bar=a.a+b.b
        """
        ).lstrip()
        == rule_runner.read_file("only_fix_imports.py")
    )

    rule_runner.write_files(
        {
            "skip_isort.py": dedent(
                """
            import b
            import a

            zap=a.a+b.b
            """
            ).lstrip(),
        }
    )
    res = rule_runner.run_goal_rule(
        Fmt, global_args=["--isort_formatter-skip"], args=["skip_isort.py"]
    )
    assert res.exit_code == 0
    assert "black_formatter made changes" in res.stderr
    assert "isort" not in res.stderr
    assert (
        dedent(
            """
        import b
        import a

        zap = a.a + b.b
        """
        ).lstrip()
        == rule_runner.read_file("skip_isort.py")
    )
