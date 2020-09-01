# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from textwrap import dedent
from typing import List, Optional, Sequence

import pytest

from pants.backend.python.lint.pylint.plugin_target_type import PylintSourcePlugin
from pants.backend.python.lint.pylint.rules import PylintFieldSet, PylintRequest
from pants.backend.python.lint.pylint.rules import rules as pylint_rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.core.goals.lint import LintResult, LintResults
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.rules import QueryRule
from pants.engine.target import Target, WrappedTarget
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.python_interpreter_selection import skip_unless_python27_and_python3_present
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[*pylint_rules(), QueryRule(LintResults, (PylintRequest, OptionsBootstrapper))],
        target_types=[PythonLibrary, PythonRequirementLibrary, PylintSourcePlugin],
    )


# See http://pylint.pycqa.org/en/latest/user_guide/run.html#exit-codes for exit codes.
PYLINT_FAILURE_RETURN_CODE = 16

PACKAGE = "src/python/project"
GOOD_SOURCE = FileContent(f"{PACKAGE}/good.py", b"'''docstring'''\nUPPERCASE_CONSTANT = ''\n")
BAD_SOURCE = FileContent(f"{PACKAGE}/bad.py", b"'''docstring'''\nlowercase_constant = ''\n")
PY3_ONLY_SOURCES = FileContent(f"{PACKAGE}/py3.py", b"'''docstring'''\nCONSTANT: str = ''\n")

GLOBAL_ARGS = (
    "--backend-packages=pants.backend.python.lint.pylint",
    "--source-root-patterns=['src/python', 'tests/python']",
)


def make_target(
    rule_runner: RuleRunner,
    source_files: List[FileContent],
    *,
    package: Optional[str] = None,
    name: str = "target",
    interpreter_constraints: Optional[str] = None,
    dependencies: Optional[List[Address]] = None,
) -> Target:
    if not package:
        package = PACKAGE
    for source_file in source_files:
        rule_runner.create_file(source_file.path, source_file.content.decode())
    source_globs = [PurePath(source_file.path).name for source_file in source_files]
    rule_runner.add_to_build_file(
        package,
        dedent(
            f"""\
            python_library(
                name={repr(name)},
                sources={source_globs},
                dependencies={[str(dep) for dep in dependencies or ()]},
                compatibility={repr(interpreter_constraints)},
            )
            """
        ),
    )
    return rule_runner.request_product(
        WrappedTarget,
        [
            Address(package, target_name=name),
            create_options_bootstrapper(args=GLOBAL_ARGS),
        ],
    ).target


def run_pylint(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
    additional_args: Optional[List[str]] = None,
) -> Sequence[LintResult]:
    args = list(GLOBAL_ARGS)
    if config:
        rule_runner.create_file(relpath="pylintrc", contents=config)
        args.append("--pylint-config=pylintrc")
    if passthrough_args:
        args.append(f"--pylint-args='{passthrough_args}'")
    if skip:
        args.append("--pylint-skip")
    if additional_args:
        args.extend(additional_args)
    results = rule_runner.request_product(
        LintResults,
        [
            PylintRequest(PylintFieldSet.create(tgt) for tgt in targets),
            create_options_bootstrapper(args=args),
        ],
    )
    return results.results


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    result = run_pylint(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_pylint(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/bad.py:2:0: C0103" in result[0].stdout


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    result = run_pylint(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/good.py" not in result[0].stdout
    assert f"{PACKAGE}/bad.py:2:0: C0103" in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE], name="t1"),
        make_target(rule_runner, [BAD_SOURCE], name="t2"),
    ]
    result = run_pylint(rule_runner, targets)
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/good.py" not in result[0].stdout
    assert f"{PACKAGE}/bad.py:2:0: C0103" in result[0].stdout


@skip_unless_python27_and_python3_present
def test_uses_correct_python_version(rule_runner: RuleRunner) -> None:
    py2_args = [
        "--pylint-version=pylint<2",
        "--pylint-extra-requirements=['setuptools<45', 'isort>=4.3.21,<4.4']",
    ]
    py2_target = make_target(
        rule_runner, [PY3_ONLY_SOURCES], name="py2", interpreter_constraints="CPython==2.7.*"
    )
    py2_result = run_pylint(rule_runner, [py2_target], additional_args=py2_args)
    assert len(py2_result) == 1
    assert py2_result[0].exit_code == 2
    assert "invalid syntax (<string>, line 2) (syntax-error)" in py2_result[0].stdout

    py3_target = make_target(
        rule_runner,
        [PY3_ONLY_SOURCES],
        name="py3",
        # NB: Avoid Python 3.8+ for this test due to issues with asteroid/ast.
        # See https://github.com/pantsbuild/pants/issues/10547.
        interpreter_constraints="CPython>=3.6,<3.8",
    )
    py3_result = run_pylint(rule_runner, [py3_target])
    assert len(py3_result) == 1
    assert py3_result[0].exit_code == 0
    assert "Your code has been rated at 10.00/10" in py3_result[0].stdout.strip()

    combined_result = run_pylint(rule_runner, [py2_target, py3_target], additional_args=py2_args)
    assert len(combined_result) == 2
    batched_py3_result, batched_py2_result = sorted(
        combined_result, key=lambda result: result.exit_code
    )

    assert batched_py2_result.exit_code == 2
    assert batched_py2_result.partition_description == "['CPython==2.7.*']"
    assert "invalid syntax (<string>, line 2) (syntax-error)" in batched_py2_result.stdout

    assert batched_py3_result.exit_code == 0
    assert batched_py3_result.partition_description == "['CPython>=3.6,<3.8']"
    assert "Your code has been rated at 10.00/10" in batched_py3_result.stdout.strip()


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_pylint(rule_runner, [target], config="[pylint]\ndisable = C0103\n")
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_pylint(rule_runner, [target], passthrough_args="--disable=C0103")
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()


def test_includes_direct_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            python_requirement_library(
                name='transitive_req',
                requirements=['django'],
            )

            python_requirement_library(
                name='direct_req',
                requirements=['ansicolors'],
            )
            """
        ),
    )
    rule_runner.add_to_build_file(PACKAGE, "python_library(name='transitive_dep', sources=[])\n")
    rule_runner.create_file(
        f"{PACKAGE}/direct_dep.py",
        dedent(
            """\
            # No docstring - Pylint doesn't lint dependencies.

            from project.transitive_dep import doesnt_matter_if_variable_exists

            THIS_VARIABLE_EXISTS = ''
            """
        ),
    )
    rule_runner.add_to_build_file(
        PACKAGE,
        dedent(
            """\
            python_library(
                name='direct_dep',
                sources=['direct_dep.py'],
                dependencies=[':transitive_dep', '//:transitive_req'],
            )
            """
        ),
    )

    source_content = dedent(
        """\
        '''Pylint will check that variables exist and are used.'''
        from colors import green
        from project.direct_dep import THIS_VARIABLE_EXISTS

        print(green(THIS_VARIABLE_EXISTS))
        """
    )
    target = make_target(
        rule_runner,
        source_files=[FileContent(f"{PACKAGE}/target.py", source_content.encode())],
        dependencies=[
            Address(PACKAGE, target_name="direct_dep"),
            Address("", target_name="direct_req"),
        ],
    )

    result = run_pylint(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_pylint(rule_runner, [target], skip=True)
    assert not result


def test_pep420_namespace_packages(rule_runner: RuleRunner) -> None:
    test_fc = FileContent(
        "tests/python/project/good_test.py",
        dedent(
            """\
            '''Docstring.'''

            from project.good import UPPERCASE_CONSTANT

            CONSTANT2 = UPPERCASE_CONSTANT
            """
        ).encode(),
    )
    targets = [
        make_target(rule_runner, [GOOD_SOURCE]),
        make_target(
            rule_runner,
            [test_fc],
            package="tests/python/project",
            dependencies=[Address.parse(f"{PACKAGE}:target")],
        ),
    ]
    result = run_pylint(rule_runner, targets)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Your code has been rated at 10.00/10" in result[0].stdout.strip()


def test_3rdparty_plugin(rule_runner: RuleRunner) -> None:
    source_content = dedent(
        """\
        '''Docstring.'''

        import unittest

        class PluginTest(unittest.TestCase):
            '''Docstring.'''

            def test_plugin(self):
                '''Docstring.'''
                self.assertEqual(True, True)
        """
    )
    target = make_target(
        rule_runner, [FileContent(f"{PACKAGE}/thirdparty_plugin.py", source_content.encode())]
    )
    result = run_pylint(
        rule_runner,
        [target],
        additional_args=["--pylint-extra-requirements=pylint-unittest>=0.1.3,<0.2"],
        passthrough_args="--load-plugins=pylint_unittest",
    )
    assert len(result) == 1
    assert result[0].exit_code == 4
    assert f"{PACKAGE}/thirdparty_plugin.py:10:8: W5301" in result[0].stdout


def test_source_plugin(rule_runner: RuleRunner) -> None:
    # NB: We make this source plugin fairly complex by having it use transitive dependencies.
    # This is to ensure that we can correctly support plugins with dependencies.
    rule_runner.add_to_build_file(
        "",
        dedent(
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
    )
    rule_runner.create_file(
        "build-support/plugins/subdir/dep.py",
        dedent(
            """\
            from colors import red

            def is_print(node):
                _ = red("Test that transitive deps are loaded.")
                return node.func.name == "print"
            """
        ),
    )
    rule_runner.add_to_build_file(
        "build-support/plugins/subdir", "python_library(dependencies=['//:colors'])"
    )
    rule_runner.create_file(
        "build-support/plugins/print_plugin.py",
        dedent(
            """\
            from pylint.checkers import BaseChecker
            from pylint.interfaces import IAstroidChecker

            from subdir.dep import is_print

            class PrintChecker(BaseChecker):
                __implements__ = IAstroidChecker
                name = "print_plugin"
                msgs = {
                    "C9871": ("`print` statements are banned", "print-statement-used", ""),
                }

                def visit_call(self, node):
                    if is_print(node):
                        self.add_message("print-statement-used", node=node)

            def register(linter):
                linter.register_checker(PrintChecker(linter))
            """
        ),
    )
    rule_runner.add_to_build_file(
        "build-support/plugins",
        dedent(
            """\
            pylint_source_plugin(
                name='print_plugin',
                sources=['print_plugin.py'],
                dependencies=['//:pylint', 'build-support/plugins/subdir'],
            )
            """
        ),
    )
    config_content = dedent(
        """\
        [MASTER]
        load-plugins=print_plugin
        """
    )
    target = make_target(
        rule_runner, [FileContent(f"{PACKAGE}/source_plugin.py", b"'''Docstring.'''\nprint()\n")]
    )
    result = run_pylint(
        rule_runner,
        [target],
        additional_args=[
            "--pylint-source-plugins=['build-support/plugins:print_plugin']",
            f"--source-root-patterns=['build-support/plugins', '{PACKAGE}']",
        ],
        config=config_content,
    )
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/source_plugin.py:2:0: C9871" in result[0].stdout
