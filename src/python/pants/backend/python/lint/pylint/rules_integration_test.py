# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.lint.pylint.rules import PylintFieldSet, PylintRequest
from pants.backend.python.lint.pylint.rules import rules as pylint_rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.core.goals.lint import LintResult, LintResults
from pants.engine.addresses import Address
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import skip_unless_python27_and_python3_present
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*pylint_rules(), QueryRule(LintResults, [PylintRequest])],
        target_types=[PythonLibrary, PythonRequirementLibrary],
    )


# See http://pylint.pycqa.org/en/latest/user_guide/run.html#exit-codes for exit codes.
PYLINT_FAILURE_RETURN_CODE = 16

PACKAGE = "src/python/project"
GOOD_FILE = "'''docstring'''\nUPPERCASE_CONSTANT = ''\n"
BAD_FILE = "'''docstring'''\nlowercase_constant = ''\n"


def run_pylint(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python.lint.pylint",
            "--source-root-patterns=['src/python', 'tests/python']",
            *(extra_args or ()),
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    results = rule_runner.request(
        LintResults,
        [PylintRequest(PylintFieldSet.create(tgt) for tgt in targets)],
    )
    return results.results


def assert_success(
    rule_runner: RuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_pylint(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert "Your code has been rated at 10.00/10" in result[0].stdout
    assert result[0].exit_code == 0


def test_passing_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": GOOD_FILE, f"{PACKAGE}/BUILD": "python_library()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(rule_runner, tgt)


def test_failing_source(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_library()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/f.py:2:0: C0103" in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/good.py": GOOD_FILE,
            f"{PACKAGE}/bad.py": BAD_FILE,
            f"{PACKAGE}/BUILD": "python_library()",
        }
    )
    tgts = [
        rule_runner.get_target(Address(PACKAGE, relative_file_path="good.py")),
        rule_runner.get_target(Address(PACKAGE, relative_file_path="bad.py")),
    ]
    result = run_pylint(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/good.py" not in result[0].stdout
    assert f"{PACKAGE}/bad.py:2:0: C0103" in result[0].stdout


@skip_unless_python27_and_python3_present
def test_uses_correct_python_version(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": "'''docstring'''\nCONSTANT: str = ''\n",
            # NB: Avoid Python 3.8+ for this test due to issues with astroid/ast.
            # See https://github.com/pantsbuild/pants/issues/10547.
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_library(name='py2', interpreter_constraints=['==2.7.*'])
                python_library(name='py3', interpreter_constraints=['CPython>=3.6,<3.8'])
                """
            ),
        }
    )

    py2_args = [
        "--pylint-version=pylint<2",
        "--pylint-extra-requirements=['setuptools<45', 'isort>=4.3.21,<4.4']",
    ]
    py2_tgt = rule_runner.get_target(Address(PACKAGE, target_name="py2", relative_file_path="f.py"))
    py2_result = run_pylint(rule_runner, [py2_tgt], extra_args=py2_args)
    assert len(py2_result) == 1
    assert py2_result[0].exit_code == 2
    assert "invalid syntax (<string>, line 2) (syntax-error)" in py2_result[0].stdout

    py3_tgt = rule_runner.get_target(Address(PACKAGE, target_name="py3", relative_file_path="f.py"))
    py3_result = run_pylint(rule_runner, [py3_tgt])
    assert len(py3_result) == 1
    assert py3_result[0].exit_code == 0
    assert "Your code has been rated at 10.00/10" in py3_result[0].stdout.strip()

    combined_result = run_pylint(rule_runner, [py2_tgt, py3_tgt], extra_args=py2_args)
    assert len(combined_result) == 2
    batched_py3_result, batched_py2_result = sorted(
        combined_result, key=lambda result: result.exit_code
    )

    assert batched_py2_result.exit_code == 2
    assert batched_py2_result.partition_description == "['CPython==2.7.*']"
    assert "invalid syntax (<string>, line 2) (syntax-error)" in batched_py2_result.stdout

    assert batched_py3_result.exit_code == 0
    assert batched_py3_result.partition_description == "['CPython<3.8,>=3.6']"
    assert "Your code has been rated at 10.00/10" in batched_py3_result.stdout.strip()


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": BAD_FILE,
            f"{PACKAGE}/BUILD": "python_library()",
            "pylintrc": "[pylint]\ndisable = C0103",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=["--pylint-config=pylintrc"])


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_library()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=["--pylint-args='--disable=C0103'"])


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_library()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint(rule_runner, [tgt], extra_args=["--pylint-skip"])
    assert not result


def test_includes_direct_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement_library(name='transitive_req', requirements=['fake'])
                python_requirement_library(name='direct_req', requirements=['ansicolors'])
                """
            ),
            f"{PACKAGE}/transitive_dep.py": "",
            f"{PACKAGE}/direct_dep.py": dedent(
                """\
                # No docstring - Pylint doesn't lint dependencies.

                from project.transitive_dep import doesnt_matter_if_variable_exists

                THIS_VARIABLE_EXISTS = ''
                """
            ),
            f"{PACKAGE}/f.py": dedent(
                """\
                '''Pylint will check that variables exist and are used.'''
                from colors import green
                from project.direct_dep import THIS_VARIABLE_EXISTS

                print(green(THIS_VARIABLE_EXISTS))
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_library(name='transitive_dep', sources=['transitive_dep.py'])
                python_library(
                    name='direct_dep',
                    sources=['direct_dep.py'],
                    dependencies=['//:transitive_req', ':transitive_dep']
                )
                python_library(sources=['f.py'], dependencies=['//:direct_req', ':direct_dep'])
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(rule_runner, tgt)


def test_pep420_namespace_packages(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": GOOD_FILE,
            f"{PACKAGE}/BUILD": "python_library()",
            "tests/python/project/f2.py": dedent(
                """\
                '''Docstring.'''

                from project.f import UPPERCASE_CONSTANT

                CONSTANT2 = UPPERCASE_CONSTANT
                """
            ),
            "tests/python/project/BUILD": f"python_library(dependencies=['{PACKAGE}'])",
        }
    )
    tgts = [
        rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py")),
        rule_runner.get_target(Address("tests/python/project", relative_file_path="f2.py")),
    ]
    result = run_pylint(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()


def test_type_stubs(rule_runner: RuleRunner) -> None:
    # If an implementation file shares the same name as a type stub, Pylint will only check the
    # implementation file. So, here, we only check running directly on a type stub.
    rule_runner.write_files({f"{PACKAGE}/f.pyi": BAD_FILE, f"{PACKAGE}/BUILD": "python_library()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.pyi"))
    result = run_pylint(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/f.pyi:2:0: C0103" in result[0].stdout


def test_3rdparty_plugin(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": dedent(
                """\
                '''Docstring.'''

                import unittest

                class PluginTest(unittest.TestCase):
                    '''Docstring.'''

                    def test_plugin(self):
                        '''Docstring.'''
                        self.assertEqual(True, True)
                """
            ),
            f"{PACKAGE}/BUILD": "python_library()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint(
        rule_runner,
        [tgt],
        extra_args=[
            "--pylint-extra-requirements=pylint-unittest>=0.1.3,<0.2",
            "--pylint-args='--load-plugins=pylint_unittest'",
        ],
    )
    assert len(result) == 1
    assert result[0].exit_code == 4
    assert f"{PACKAGE}/f.py:10:8: W5301" in result[0].stdout


def test_source_plugin(rule_runner: RuleRunner) -> None:
    # NB: We make this source plugin fairly complex by having it use transitive dependencies.
    # This is to ensure that we can correctly support plugins with dependencies.
    # The plugin bans `print()`.
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement_library(
                    name='pylint',
                    requirements=['pylint>=2.4.4,<2.5'],
                )

                python_requirement_library(
                    name='colors',
                    requirements=['ansicolors'],
                )
                """
            ),
            "pants-plugins/plugins/subdir/dep.py": dedent(
                """\
                from colors import red

                def is_print(node):
                    _ = red("Test that transitive deps are loaded.")
                    return hasattr(node.func, "name") and node.func.name == "print"
                """
            ),
            "pants-plugins/plugins/subdir/BUILD": "python_library(dependencies=['//:colors'])",
            "pants-plugins/plugins/print_plugin.py": dedent(
                """\
                '''Docstring.'''

                from pylint.checkers import BaseChecker
                from pylint.interfaces import IAstroidChecker

                from subdir.dep import is_print

                class PrintChecker(BaseChecker):
                    '''Docstring.'''

                    __implements__ = IAstroidChecker
                    name = "print_plugin"
                    msgs = {
                        "C9871": ("`print` statements are banned", "print-statement-used", ""),
                    }

                    def visit_call(self, node):
                        '''Docstring.'''
                        if is_print(node):
                            self.add_message("print-statement-used", node=node)


                def register(linter):
                    '''Docstring.'''
                    linter.register_checker(PrintChecker(linter))
                """
            ),
            "pants-plugins/plugins/BUILD": (
                "python_library(dependencies=['//:pylint', 'pants-plugins/plugins/subdir'])"
            ),
            "pylintrc": dedent(
                """\
                [MASTER]
                load-plugins=print_plugin
                """
            ),
            f"{PACKAGE}/f.py": "'''Docstring.'''\nprint()\n",
            f"{PACKAGE}/BUILD": "python_library()",
        }
    )

    def run_pylint_with_plugin(tgt: Target) -> LintResult:
        res = run_pylint(
            rule_runner,
            [tgt],
            extra_args=[
                "--pylint-source-plugins=['pants-plugins/plugins']",
                f"--source-root-patterns=['pants-plugins/plugins', '{PACKAGE}']",
                "--pylint-config=pylintrc",
            ],
        )
        assert len(res) == 1
        return res[0]

    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint_with_plugin(tgt)
    assert result.exit_code == PYLINT_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/f.py:2:0: C9871" in result.stdout

    # Ensure that running Pylint on the plugin itself still works.
    plugin_tgt = rule_runner.get_target(
        Address("pants-plugins/plugins", relative_file_path="print_plugin.py")
    )
    result = run_pylint_with_plugin(plugin_tgt)
    assert result.exit_code == 0
    assert "Your code has been rated at 10.00/10" in result.stdout
