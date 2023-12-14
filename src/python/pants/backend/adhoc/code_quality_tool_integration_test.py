# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent  # noqa: PNT20

import pytest

from pants.backend.adhoc.code_quality_tool import (
    CodeQualityToolBackend,
    CodeQualityToolTarget,
    CodeQualityToolUnsupportedGoalError,
    base_rules,
)
from pants.backend.python import register as register_python
from pants.backend.python.target_types import PythonSourceTarget
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
        CodeQualityToolBackend(
            goal="package", target="build-support:flake8_tool", name="Flake8", scope="flake8_tool"
        )


def make_rule_runner(*cfgs: CodeQualityToolBackend):
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
            FileTarget,
            PythonSourceTarget,
        ],
        rules=rules,
    )


def test_lint_tool():
    cfg = CodeQualityToolBackend(
        goal="lint", target="build-support:no_badcode_tool", name="No Bad Code", scope="nobadcode"
    )

    rule_runner = make_rule_runner(cfg)

    # linter is a python script that detects the presence
    # of a configurable list of problem strings
    rule_runner.write_files(
        {
            "build-support/BUILD": dedent(
                """
            python_source(name="no_badcode", source="no_badcode.py")
            file(name="badcode_conf", source="badcode.conf")

            code_quality_tool(
                name="no_badcode_tool",
                runnable=":no_badcode",
                execution_dependencies=[":badcode_conf"],
                file_glob_include=["**/*.py"],
                file_glob_exclude=["messy_ignored_dir/**", "build-support/**"],
                args=["build-support/badcode.conf"],
            )
            """
            ),
            "build-support/no_badcode.py": dedent(
                """
            import sys

            config_file = sys.argv[1]
            with open(config_file) as cfgfile:
                badcode_strings = cfgfile.read().strip().split(",")

            failed = False
            for fpath in sys.argv[2:]:
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


def test_fix_tool():
    cfg = CodeQualityToolBackend(
        goal="fix", target="//:bad_to_good_tool", name="Bad to Good", scope="badtogood"
    )

    rule_runner = make_rule_runner(cfg)

    # Fixer replaces the string 'badcode' with 'goodcode'
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
            python_source(name="bad_to_good", source="bad_to_good.py")

            code_quality_tool(
                name="bad_to_good_tool",
                runnable=":bad_to_good",
                file_glob_include=["**/*.py"],
                file_glob_exclude=["bad_to_good.py"],
            )
            """
            ),
            "bad_to_good.py": dedent(
                """
            import sys

            for fpath in sys.argv[1:]:
                with open(fpath) as f:
                    contents = f.read()
                if 'badcode' in contents:
                    with open(fpath, 'w') as f:
                        f.write(contents.replace('badcode', 'goodcode'))
                """
            ),
            "good_fmt.py": "thisisfine = 5\n",
            "needs_repair.py": "badcode = 10\n",
        }
    )

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 1
    assert "badtogood failed" in res.stderr

    res = rule_runner.run_goal_rule(Fix, args=["::"])
    assert res.exit_code == 0
    assert "badtogood made changes" in res.stderr

    assert "goodcode = 10\n" == rule_runner.read_file("needs_repair.py")

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 0
    assert "badtogood succeeded" in res.stderr


def test_several_formatters():
    bad_to_good_cfg = CodeQualityToolBackend(
        goal="fmt", target="//:bad_to_good_tool", name="Bad to Good", scope="badtogood"
    )

    underscoreit_cfg = CodeQualityToolBackend(
        goal="fmt", target="//:underscore_it_tool", name="Underscore It", scope="underscoreit"
    )

    rule_runner = make_rule_runner(bad_to_good_cfg, underscoreit_cfg)

    # One formatter replaces the string 'badcode' with 'goodcode'
    # The other adds an underscore to 'goodcode' -> 'good_code'
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
            python_source(name="bad_to_good", source="bad_to_good.py")
            python_source(name="underscore_it", source="underscore_it.py")

            code_quality_tool(
                name="bad_to_good_tool",
                runnable=":bad_to_good",
                file_glob_include=["**/*.py"],
                file_glob_exclude=["underscore_it.py", "bad_to_good.py"],
            )

            code_quality_tool(
                name="underscore_it_tool",
                runnable=":underscore_it",
                file_glob_include=["**/*.py"],
                file_glob_exclude=["underscore_it.py", "bad_to_good.py"],
            )
            """
            ),
            "bad_to_good.py": dedent(
                """
            import sys

            for fpath in sys.argv[1:]:
                with open(fpath) as f:
                    contents = f.read()
                if 'badcode' in contents:
                    with open(fpath, 'w') as f:
                        f.write(contents.replace('badcode', 'goodcode'))
                """
            ),
            "underscore_it.py": dedent(
                """
            import sys

            for fpath in sys.argv[1:]:
                with open(fpath) as f:
                    contents = f.read()
                if 'goodcode' in contents:
                    with open(fpath, 'w') as f:
                        f.write(contents.replace('goodcode', 'good_code'))
                """
            ),
            "needs_repair.py": "badcode = 10\n",
        }
    )

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 1
    assert "badtogood failed" in res.stderr
    assert "underscoreit succeeded" in res.stderr

    res = rule_runner.run_goal_rule(Fmt, args=["::"])
    assert res.exit_code == 0
    assert "badtogood made changes" in res.stderr
    assert "underscoreit made changes" in res.stderr

    assert "good_code = 10\n" == rule_runner.read_file("needs_repair.py")

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 0
    assert "badtogood succeeded" in res.stderr
    assert "underscoreit succeeded" in res.stderr

    rule_runner.write_files({"only_fix_underscores.py": "goodcode = 5\nbadcode = 10\n"})
    res = rule_runner.run_goal_rule(Fmt, args=["--only=underscoreit", "only_fix_underscores.py"])
    assert res.exit_code == 0
    assert "underscoreit made changes" in res.stderr
    assert "badtogood" not in res.stderr
    assert "good_code = 5\nbadcode = 10\n" == rule_runner.read_file("only_fix_underscores.py")

    rule_runner.write_files({"do_not_underscore.py": "goodcode = 50\nbadcode = 100\n"})

    res = rule_runner.run_goal_rule(
        Fmt, global_args=["--underscoreit-skip"], args=["do_not_underscore.py"]
    )
    assert res.exit_code == 0
    assert "badtogood made changes" in res.stderr
    assert "underscoreit" not in res.stderr
    assert "goodcode = 50\ngoodcode = 100\n" == rule_runner.read_file("do_not_underscore.py")
