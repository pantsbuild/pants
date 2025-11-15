# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.pylint import subsystem
from pants.backend.python.lint.pylint.rules import PartitionMetadata, PylintRequest
from pants.backend.python.lint.pylint.rules import rules as pylint_rules
from pants.backend.python.lint.pylint.subsystem import Pylint, PylintFieldSet
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.lint import LintResult, Partitions
from pants.core.util_rules import config_files
from pants.core.util_rules.partitions import Partition
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import (
    all_major_minor_python_versions,
    skip_unless_python39_present,
    skip_unless_python310_and_python311_present,
)
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule
from pants.util.resources import read_resource, read_sibling_resource


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *pylint_rules(),
            *subsystem.rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(Partitions, [PylintRequest.PartitionRequest]),
            QueryRule(LintResult, [PylintRequest.Batch]),
        ],
        target_types=[PythonSourceTarget, PythonSourcesGeneratorTarget, PythonRequirementTarget],
    )


# See http://pylint.pycqa.org/en/latest/user_guide/run.html#exit-codes for exit codes.
PYLINT_ERROR_FAILURE_RETURN_CODE = 2
PYLINT_CONVENTION_FAILURE_RETURN_CODE = 16

PACKAGE = "src/python/project"
GOOD_FILE = "'''docstring'''\nUPPERCASE_CONSTANT = ''\n"
BAD_FILE = "'''docstring'''\nlowercase_constant = ''\n"


def run_pylint(
    rule_runner: PythonRuleRunner,
    targets: list[Target],
    *,
    python_ics: str | None = Pylint.default_interpreter_constraints[0],
    extra_args: list[str] | None = None,
) -> tuple[LintResult, ...]:
    args = extra_args or []
    if python_ics:
        args.extend([f"--python-interpreter-constraints=['{python_ics}']"])
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python.lint.pylint",
            "--source-root-patterns=['src/python', 'tests/python']",
            *(args),
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    partitions = rule_runner.request(
        Partitions[PylintFieldSet, PartitionMetadata],
        [PylintRequest.PartitionRequest(tuple(PylintFieldSet.create(tgt) for tgt in targets))],
    )
    results: list[LintResult] = []
    for partition in partitions:
        result = rule_runner.request(
            LintResult,
            [PylintRequest.Batch("", partition.elements, partition.metadata)],
        )
        results.append(result)
    return tuple(results)


def assert_success(rule_runner: PythonRuleRunner, target: Target, *, extra_args: list[str]) -> None:
    result = run_pylint(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert "Your code has been rated at 10.00/10" in result[0].stdout
    assert result[0].exit_code == 0
    assert result[0].report == EMPTY_DIGEST


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(Pylint.default_interpreter_constraints),
)
def test_passing(rule_runner: PythonRuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": GOOD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(
        rule_runner,
        tgt,
        extra_args=[f"--pylint-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )


def test_failing(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_CONVENTION_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/f.py:2:0: C0103" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_report_file(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint(
        rule_runner, [tgt], extra_args=["--pylint-args='--output=reports/output.txt'"]
    )
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_CONVENTION_FAILURE_RETURN_CODE
    assert result[0].stdout.strip() == ""
    report_files = rule_runner.request(DigestContents, [result[0].report])
    assert len(report_files) == 1
    assert f"{PACKAGE}/f.py:2:0: C0103" in report_files[0].content.decode()


def test_multiple_targets(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/good.py": GOOD_FILE,
            f"{PACKAGE}/bad.py": BAD_FILE,
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgts = [
        rule_runner.get_target(Address(PACKAGE, relative_file_path="good.py")),
        rule_runner.get_target(Address(PACKAGE, relative_file_path="bad.py")),
    ]
    result = run_pylint(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_CONVENTION_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/good.py" not in result[0].stdout
    assert f"{PACKAGE}/bad.py:2:0: C0103" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


@skip_unless_python310_and_python311_present
def test_uses_correct_python_version(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            # ExceptionGroup was introduced in 3.11.
            f"{PACKAGE}/f.py": "'''docstring'''\neg = ExceptionGroup('', [Exception()])\n",
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_sources(name='py310', interpreter_constraints=['CPython==3.10.*'])
                python_sources(name='py311', interpreter_constraints=['CPython==3.11.*'])
                """
            ),
        }
    )

    py310_tgt = rule_runner.get_target(
        Address(PACKAGE, target_name="py310", relative_file_path="f.py")
    )
    py310_result = run_pylint(rule_runner, [py310_tgt], python_ics=None)
    assert len(py310_result) == 1
    assert py310_result[0].exit_code == 2
    assert (
        "E0602: Undefined variable 'ExceptionGroup' (undefined-variable)" in py310_result[0].stdout
    )

    py311_tgt = rule_runner.get_target(
        Address(PACKAGE, target_name="py311", relative_file_path="f.py")
    )
    py311_result = run_pylint(rule_runner, [py311_tgt], python_ics=None)
    assert len(py311_result) == 1
    assert py311_result[0].exit_code == 0
    assert "Your code has been rated at 10.00/10" in py311_result[0].stdout.strip()

    combined_result = run_pylint(rule_runner, [py310_tgt, py311_tgt], python_ics=None)
    assert len(combined_result) == 2
    batched_py311_result, batched_py310_result = sorted(
        combined_result, key=lambda result: result.exit_code
    )

    assert batched_py310_result.exit_code == 2
    assert batched_py310_result.partition_description == "['CPython==3.10.*']"
    assert (
        "E0602: Undefined variable 'ExceptionGroup' (undefined-variable)"
        in batched_py310_result.stdout
    )

    assert batched_py311_result.exit_code == 0
    assert batched_py311_result.partition_description == "['CPython==3.11.*']"
    assert "Your code has been rated at 10.00/10" in batched_py311_result.stdout.strip()


@pytest.mark.parametrize(
    "config_path,extra_args",
    (["pylintrc", []], ["custom_config.ini", ["--pylint-config=custom_config.ini"]]),
)
def test_config_file(
    rule_runner: PythonRuleRunner, config_path: str, extra_args: list[str]
) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": BAD_FILE,
            f"{PACKAGE}/BUILD": "python_sources()",
            config_path: "[pylint]\ndisable = C0103",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=extra_args)


def test_passthrough_args(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(rule_runner, tgt, extra_args=["--pylint-args='--disable=C0103'"])


def test_skip(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint(rule_runner, [tgt], extra_args=["--pylint-skip"])
    assert not result


def test_includes_transitive_dependencies(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(name='transitive_req', requirements=['freezegun'])
                python_requirement(name='direct_req', requirements=['ansicolors'])
                """
            ),
            f"{PACKAGE}/transitive_dep.py": dedent(
                """\
                import freezegun

                A = NotImplemented
                """
            ),
            f"{PACKAGE}/direct_dep.py": dedent(
                """\
                # No docstring - Pylint doesn't lint dependencies.

                from project.transitive_dep import A

                B = A
                """
            ),
            f"{PACKAGE}/f.py": dedent(
                """\
                '''Pylint should be upset about raising NotImplemented.'''
                from colors import green
                from project.direct_dep import B

                def i_just_raise():
                    '''A docstring.'''
                    print(green("hello"))
                    raise B  # pylint should error here
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_source(
                    name='transitive_dep',
                    source='transitive_dep.py',
                    dependencies=['//:transitive_req'],
                )
                python_source(
                    name='direct_dep',
                    source='direct_dep.py',
                    dependencies=[':transitive_dep']
                )
                python_source(
                    name="f",
                    source='f.py',
                    dependencies=['//:direct_req', ':direct_dep'],
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, target_name="f"))
    result = run_pylint(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_ERROR_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/f.py:8:4: E0702" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_pep420_namespace_packages(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": GOOD_FILE,
            f"{PACKAGE}/BUILD": "python_sources()",
            "tests/python/project/f2.py": dedent(
                """\
                '''Docstring.'''

                from project.f import UPPERCASE_CONSTANT

                CONSTANT2 = UPPERCASE_CONSTANT
                """
            ),
            "tests/python/project/BUILD": f"python_sources(dependencies=['{PACKAGE}'])",
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
    assert result[0].report == EMPTY_DIGEST


def test_type_stubs(rule_runner: PythonRuleRunner) -> None:
    # If an implementation file shares the same name as a type stub, Pylint will only check the
    # implementation file. So, here, we only check running directly on a type stub.
    rule_runner.write_files({f"{PACKAGE}/f.pyi": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.pyi"))
    result = run_pylint(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == PYLINT_CONVENTION_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/f.pyi:2:0: C0103" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_3rdparty_plugin(rule_runner: PythonRuleRunner) -> None:
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
            f"{PACKAGE}/BUILD": "python_sources()",
            "pylint.lock": read_resource(
                "pants.backend.python.lint.pylint", "pylint_3rdparty_plugin_test.lock"
            ),
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint(
        rule_runner,
        [tgt],
        extra_args=[
            "--python-resolves={'pylint':'pylint.lock'}",
            "--pylint-install-from-resolve=pylint",
            "--pylint-args='--load-plugins=pylint_unittest'",
        ],
    )
    assert len(result) == 1
    assert result[0].exit_code == 4
    assert f"{PACKAGE}/f.py:10:8: W5301" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_source_plugin(rule_runner: PythonRuleRunner) -> None:
    # NB: We make this source plugin fairly complex by having it use transitive dependencies.
    # This is to ensure that we can correctly support plugins with dependencies.
    # The plugin bans `print()`.
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(name='pylint', requirements=['pylint>=2.13.0,<2.15'])
                python_requirement(name='colors', requirements=['ansicolors'])
                """
            ),
            "pylint.lock": read_sibling_resource(__name__, "pylint_source_plugin_test.lock"),
            "pants-plugins/plugins/subdir/dep.py": dedent(
                """\
                from colors import red

                def is_print(node):
                    _ = red("Test that transitive deps are loaded.")
                    return hasattr(node.func, "name") and node.func.name == "print"
                """
            ),
            "pants-plugins/plugins/subdir/BUILD": "python_sources(dependencies=['//:colors'])",
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
                "python_sources(dependencies=['//:pylint', 'pants-plugins/plugins/subdir'])"
            ),
            "pylintrc": dedent(
                """\
                [MASTER]
                load-plugins=print_plugin
                """
            ),
            f"{PACKAGE}/f.py": "'''Docstring.'''\nprint()\n",
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )

    def run_pylint_with_plugin(tgt: Target) -> LintResult:
        res = run_pylint(
            rule_runner,
            [tgt],
            extra_args=[
                "--pylint-source-plugins=['pants-plugins/plugins']",
                f"--source-root-patterns=['pants-plugins/plugins', '{PACKAGE}']",
                "--python-resolves={'pylint':'pylint.lock'}",
                "--pylint-install-from-resolve=pylint",
            ],
        )
        assert len(res) == 1
        return res[0]

    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint_with_plugin(tgt)
    assert result.exit_code == PYLINT_CONVENTION_FAILURE_RETURN_CODE
    assert f"{PACKAGE}/f.py:2:0: C9871" in result.stdout
    assert result.report == EMPTY_DIGEST

    # Ensure that running Pylint on the plugin itself still works.
    plugin_tgt = rule_runner.get_target(
        Address("pants-plugins/plugins", relative_file_path="print_plugin.py")
    )
    result = run_pylint_with_plugin(plugin_tgt)
    print(result.stdout)
    assert result.exit_code == 0
    assert "Your code has been rated at 10.00/10" in result.stdout
    assert result.report == EMPTY_DIGEST


@skip_unless_python310_and_python311_present
def test_partition_targets(rule_runner: PythonRuleRunner) -> None:
    def create_folder(folder: str, resolve: str, interpreter: str) -> dict[str, str]:
        return {
            f"{folder}/dep.py": "",
            f"{folder}/root.py": "",
            f"{folder}/BUILD": dedent(
                f"""\
                python_source(
                    name='dep',
                    source='dep.py',
                    resolve='{resolve}',
                    interpreter_constraints=['=={interpreter}.*'],
                )
                python_source(
                    name='root',
                    source='root.py',
                    resolve='{resolve}',
                    interpreter_constraints=['=={interpreter}.*'],
                    dependencies=[':dep'],
                )
                """
            ),
        }

    files = {
        **create_folder("resolveA_py310", "a", "3.10"),
        **create_folder("resolveA_py311", "a", "3.11"),
        **create_folder("resolveB_1", "b", "3.11"),
        **create_folder("resolveB_2", "b", "3.11"),
    }
    rule_runner.write_files(files)
    rule_runner.set_options(
        ["--python-resolves={'a': '', 'b': ''}", "--python-enable-resolves"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    resolve_a_py310_dep = rule_runner.get_target(Address("resolveA_py310", target_name="dep"))
    resolve_a_py310_root = rule_runner.get_target(Address("resolveA_py310", target_name="root"))
    resolve_a_py311_dep = rule_runner.get_target(Address("resolveA_py311", target_name="dep"))
    resolve_a_py311_root = rule_runner.get_target(Address("resolveA_py311", target_name="root"))
    resolve_b_dep1 = rule_runner.get_target(Address("resolveB_1", target_name="dep"))
    resolve_b_root1 = rule_runner.get_target(Address("resolveB_1", target_name="root"))
    resolve_b_dep2 = rule_runner.get_target(Address("resolveB_2", target_name="dep"))
    resolve_b_root2 = rule_runner.get_target(Address("resolveB_2", target_name="root"))
    request: PylintRequest.PartitionRequest[PylintFieldSet] = PylintRequest.PartitionRequest(
        tuple(
            PylintFieldSet.create(t)
            for t in (
                resolve_a_py310_root,
                resolve_a_py311_root,
                resolve_b_root1,
                resolve_b_root2,
            )
        )
    )

    partitions = list(rule_runner.request(Partitions[PylintFieldSet, PartitionMetadata], [request]))
    assert len(partitions) == 3

    def assert_partition(
        partition: Partition,
        roots: list[Target],
        deps: list[Target],
        interpreter: str,
        resolve: str,
    ) -> None:
        assert partition.metadata is not None
        key = partition.metadata

        root_addresses = {t.address for t in roots}
        assert {t.address for t in key.coarsened_targets.closure()} == {
            *root_addresses,
            *(t.address for t in deps),
        }
        ics = [f"CPython=={interpreter}.*"]
        assert key.interpreter_constraints == InterpreterConstraints(ics)
        assert key.description == f"{resolve}, {ics}"

    assert_partition(partitions[0], [resolve_a_py310_root], [resolve_a_py310_dep], "3.10", "a")
    assert_partition(partitions[1], [resolve_a_py311_root], [resolve_a_py311_dep], "3.11", "a")
    assert_partition(
        partitions[2],
        [resolve_b_root1, resolve_b_root2],
        [resolve_b_dep1, resolve_b_dep2],
        "3.11",
        "b",
    )


@skip_unless_python39_present
def test_works_on_python39(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": dedent(
                """\
                x = 0
                if y := x:
                    print("x is truthy and now assigned to y")
                """
            ),
            f"{PACKAGE}/BUILD": "python_sources(interpreter_constraints=['==3.9.*'])",
            "pylint.lock": read_sibling_resource(__name__, "pylint_py39.lock"),
        }
    )
    extra_args = [
        "--python-resolves={'pylint':'pylint.lock'}",
        "--pylint-install-from-resolve=pylint",
    ]
    rule_runner.write_files({f"{PACKAGE}/f.py": GOOD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pylint(rule_runner, [tgt], python_ics="CPython==3.9.*", extra_args=extra_args)
    assert len(result) == 1
    assert "Your code has been rated at 10.00/10" in result[0].stdout
    assert result[0].exit_code == 0
    assert result[0].report == EMPTY_DIGEST
