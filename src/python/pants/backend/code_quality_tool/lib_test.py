# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent  # noqa: PNT20

from pants.backend.code_quality_tool.lib import CodeQualityToolRuleBuilder, CodeQualityToolTarget
from pants.backend.project_info.list_targets import List
from pants.backend.project_info.list_targets import rules as list_rules
from pants.backend.python import register as register_python
from pants.backend.python.target_types import PythonRequirementTarget
from pants.core.goals.fmt import Fmt
from pants.core.goals.lint import Lint
from pants.core.register import rules as core_rules
from pants.core.target_types import FileTarget
from pants.core.util_rules import adhoc_process_support, source_files
from pants.engine import process
from pants.testutil.rule_runner import RuleRunner


def test_lint_built_rule():
    cfg = CodeQualityToolRuleBuilder(
        goal="lint", target="build-support:flake8_tool", name="Flake8", scope="flake8_tool"
    )

    code_quality_tool_rules = cfg.build_rules()

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

    rule_runner.write_files(
        {
            "build-support/BUILD": dedent(
                """
            python_requirement(
                name="flake8",
                requirements=["flake8==5.0.4"]
            )
        
            code_quality_tool(
                name="flake8_tool",
                runnable=":flake8",
                execution_dependencies=[":flake8_conf"],
                file_glob_include=["**/*.py"],
                file_glob_exclude=["messy_ignored_dir/**"],
                args=["--config=build-support/.flake8", "--indent-size=2"],
            )
            
            file(
                name="flake8_conf",
                source=".flake8"
            )
            """
            ),
            "build-support/.flake8": dedent(
                """
            [flake8]
            extend-ignore = F401
            """
            ),
            "good_fmt.py": "foo = 5\n",
            "unused_import_saved_by_conf.py": "import os\n",
            "messy_ignored_dir/messy_file.py": "ignoreme=10",
            "not_a_dot_py_file.nopy": "notpy=100",
            "indent_2_ok_by_cmd_arg.py": dedent(
                """
            def foo():
              return 2
            """
            ),
        }
    )

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 0
    assert "flake8_tool succeeded" in res.stderr

    res = rule_runner.run_goal_rule(Lint, args=["good_fmt.py"])
    assert res.exit_code == 0
    assert "flake8_tool succeeded" in res.stderr

    rule_runner.write_files({"bad_fmt.py": "baz=5\n"})

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
    cfg = CodeQualityToolRuleBuilder(
        goal="fmt", target="//:black_tool", name="Black", scope="black_formatter"
    )

    code_quality_tool_rules = cfg.build_rules()

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
    assert "black_formatter failed" in res.stderr

    res = rule_runner.run_goal_rule(Fmt, args=["::"])
    assert res.exit_code == 0
    assert "black_formatter made changes" in res.stderr

    assert "bar = 10\n" == rule_runner.read_file("needs_repair.py")

    res = rule_runner.run_goal_rule(Lint, args=["::"])
    assert res.exit_code == 0
    assert "black_formatter succeeded" in res.stderr


def test_several_formatters():
    black_cfg = CodeQualityToolRuleBuilder(
        goal="fmt", target="//:black_tool", name="Black", scope="black_formatter"
    )

    isort_cfg = CodeQualityToolRuleBuilder(
        goal="fmt", target="//:isort_tool", name="isort", scope="isort_formatter"
    )

    rule_runner = RuleRunner(
        target_types=[CodeQualityToolTarget, PythonRequirementTarget, FileTarget],
        rules=[
            *source_files.rules(),
            *core_rules(),
            *process.rules(),
            *list_rules(),
            *adhoc_process_support.rules(),
            *register_python.rules(),
            *black_cfg.build_rules(),
            *isort_cfg.build_rules(),
        ],
        preserve_tmpdirs=True,
    )

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
