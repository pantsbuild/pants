# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals import package_pex_binary, pytest_runner, setup_py
from pants.backend.python.goals.coverage_py import create_or_update_coverage_config
from pants.backend.python.goals.pytest_runner import PytestPluginSetup, PytestPluginSetupRequest
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.pytest import PythonTestFieldSet
from pants.backend.python.subsystems.pytest import rules as pytest_subsystem_rules
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.subsystems.setuptools import rules as setuptools_rules
from pants.backend.python.target_types import (
    PexBinary,
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonTestsGeneratorTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.backend.python.util_rules import local_dists, pex_from_targets
from pants.core.goals.test import (
    TestDebugRequest,
    TestResult,
    build_runtime_package_dependencies,
    get_filtered_environment,
)
from pants.core.util_rules import config_files, distdir
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent
from pants.engine.rules import Get, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.testutil.python_interpreter_selection import (
    all_major_minor_python_versions,
    skip_unless_python27_and_python3_present,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner, mock_console


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            build_runtime_package_dependencies,
            create_or_update_coverage_config,
            *pytest_runner.rules(),
            *pytest_subsystem_rules(),
            *pex_from_targets.rules(),
            *dependency_inference_rules.rules(),
            *distdir.rules(),
            *config_files.rules(),
            *package_pex_binary.rules(),
            get_filtered_environment,
            *target_types_rules.rules(),
            *local_dists.rules(),
            *setup_py.rules(),
            *setuptools_rules(),
            QueryRule(TestResult, (PythonTestFieldSet,)),
            QueryRule(TestDebugRequest, (PythonTestFieldSet,)),
        ],
        target_types=[
            PexBinary,
            PythonSourcesGeneratorTarget,
            PythonTestsGeneratorTarget,
            PythonTestUtilsGeneratorTarget,
            PythonRequirementTarget,
            PythonDistribution,
        ],
        objects={"python_artifact": PythonArtifact},
    )


SOURCE_ROOT = "tests/python"
PACKAGE = os.path.join(SOURCE_ROOT, "pants_test")

GOOD_TEST = dedent(
    """\
    def test():
        pass
    """
)


def run_pytest(
    rule_runner: RuleRunner,
    test_target: Target,
    *,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> TestResult:
    args = [
        "--backend-packages=pants.backend.python",
        f"--source-root-patterns={SOURCE_ROOT}",
        *(extra_args or ()),
    ]
    rule_runner.set_options(args, env=env, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    inputs = [PythonTestFieldSet.create(test_target)]
    test_result = rule_runner.request(TestResult, inputs)
    debug_request = rule_runner.request(TestDebugRequest, inputs)
    if debug_request.process is not None:
        with mock_console(rule_runner.options_bootstrapper):
            debug_result = rule_runner.run_interactive_process(debug_request.process)
            assert test_result.exit_code == debug_result.exit_code
    return test_result


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(PythonSetup.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files(
        {f"{PACKAGE}/tests.py": GOOD_TEST, f"{PACKAGE}/BUILD": "python_tests()"}
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(
        rule_runner,
        tgt,
        extra_args=[f"--python-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert result.xml_results is not None
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/tests.py": dedent(
                """\
                def test():
                    assert False
                """
            ),
            f"{PACKAGE}/BUILD": "python_tests()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 1
    assert f"{PACKAGE}/tests.py F" in result.stdout


def test_dependencies(rule_runner: RuleRunner) -> None:
    """Ensure direct and transitive dependencies work."""
    rule_runner.write_files(
        {
            f"{PACKAGE}/__init__.py": "",
            f"{PACKAGE}/lib1.py": dedent(
                """\
                def add_one(x):
                    return x + 1
                """
            ),
            f"{PACKAGE}/lib2.py": dedent(
                """\
                from colors import red

                def add_two(x):
                    return x + 2
                """
            ),
            f"{PACKAGE}/lib3.py": dedent(
                """\
                from pants_test.lib2 import add_two

                def add_three(x):
                    return add_two(x) + 1
                """
            ),
            f"{PACKAGE}/tests.py": dedent(
                """\
                from pants_test.lib1 import add_one
                from .lib2 import add_two
                from pants_test.lib3 import add_three
                from ordered_set import OrderedSet

                def test():
                    assert add_one(1) == 2
                    assert add_two(1) == 3
                    assert add_three(1) == 4
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_tests()
                python_sources(name="lib")
                python_requirement(
                    name="reqs", requirements=["ansicolors==1.1.8", "ordered-set==3.1.1"]
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout


@skip_unless_python27_and_python3_present
def test_uses_correct_python_version(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/tests.py": dedent(
                """\
                def test() -> None:
                  pass
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_tests(name='py2', interpreter_constraints=['==2.7.*'])
                python_tests(name='py3', interpreter_constraints=['>=3.6.*'])
                """
            ),
        }
    )
    extra_args = ["--pytest-version=pytest>=4.6.6,<4.7", "--pytest-lockfile=<none>"]

    py2_tgt = rule_runner.get_target(
        Address(PACKAGE, target_name="py2", relative_file_path="tests.py")
    )
    result = run_pytest(rule_runner, py2_tgt, extra_args=extra_args)
    assert result.exit_code == 2
    assert "SyntaxError: invalid syntax" in result.stdout

    py3_tgt = rule_runner.get_target(
        Address(PACKAGE, target_name="py3", relative_file_path="tests.py")
    )
    result = run_pytest(rule_runner, py3_tgt, extra_args=extra_args)
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/tests.py": dedent(
                """\
                def test_run_me():
                  pass

                def test_ignore_me():
                  pass
                """
            ),
            f"{PACKAGE}/BUILD": "python_tests()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(rule_runner, tgt, extra_args=["--pytest-args='-k test_run_me'"])
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout
    assert "collected 2 items / 1 deselected / 1 selected" in result.stdout


def test_config_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "pytest.ini": dedent(
                """\
                [pytest]
                addopts = -s
                """
            ),
            f"{PACKAGE}/tests.py": dedent(
                """\
                def test():
                    print("All good!")
                """
            ),
            f"{PACKAGE}/BUILD": "python_tests()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0
    assert "All good!" in result.stdout and "Captured" not in result.stdout


def test_force(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {f"{PACKAGE}/tests.py": GOOD_TEST, f"{PACKAGE}/BUILD": "python_tests()"}
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))

    # Should not receive a memoized result if force=True.
    result_one = run_pytest(rule_runner, tgt, extra_args=["--test-force"])
    result_two = run_pytest(rule_runner, tgt, extra_args=["--test-force"])
    assert result_one.exit_code == 0
    assert result_two.exit_code == 0
    assert result_one is not result_two

    # But should if force=False.
    result_one = run_pytest(rule_runner, tgt)
    result_two = run_pytest(rule_runner, tgt)
    assert result_one.exit_code == 0
    assert result_one is result_two


def test_extra_output(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {f"{PACKAGE}/tests.py": GOOD_TEST, f"{PACKAGE}/BUILD": "python_tests()"}
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(
        rule_runner,
        tgt,
        extra_args=[
            "--pytest-args='--html=extra-output/report.html'",
            "--pytest-extra-requirements=pytest-html==3.1",
            # pytest-html requires setuptools to be installed because it does not use PEP 517.
            "--pytest-extra-requirements=setuptools",
            "--pytest-lockfile=<none>",
        ],
    )
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout
    assert result.extra_output is not None
    digest_contents = rule_runner.request(DigestContents, [result.extra_output.digest])
    paths = {dc.path for dc in digest_contents}
    assert {"assets/style.css", "report.html"} == paths


def test_coverage(rule_runner: RuleRunner) -> None:
    # Note that we test that rewriting the pyproject.toml doesn't cause a collision
    # between the two code paths by which we pick up that file (coverage and pytest).
    rule_runner.write_files(
        {
            "pyproject.toml": "[tool.coverage.report]\n[tool.pytest.ini_options]",
            f"{PACKAGE}/tests.py": GOOD_TEST,
            f"{PACKAGE}/BUILD": "python_tests()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(rule_runner, tgt, extra_args=["--test-use-coverage"])
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout
    assert result.coverage_data is not None


def test_conftest_dependency_injection(rule_runner: RuleRunner) -> None:
    # See `test_skip_tests` for a test that we properly skip running on conftest.py.
    rule_runner.write_files(
        {
            f"{SOURCE_ROOT}/conftest.py": dedent(
                """\
                def pytest_runtest_setup(item):
                    print('In conftest!')
                """
            ),
            f"{SOURCE_ROOT}/BUILD": "python_test_utils()",
            f"{PACKAGE}/tests.py": GOOD_TEST,
            f"{PACKAGE}/BUILD": "python_tests()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(rule_runner, tgt, extra_args=["--pytest-args='-s'"])
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py In conftest!\n." in result.stdout


def test_execution_slot_variable(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/test_concurrency_slot.py": dedent(
                """\
                import os

                def test_fail_printing_slot_env_var():
                    slot = os.getenv("SLOT")
                    print(f"Value of slot is {slot}")
                    # Deliberately fail the test so the SLOT output gets printed to stdout
                    assert 1 == 2
                """
            ),
            f"{PACKAGE}/BUILD": "python_tests()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="test_concurrency_slot.py"))
    result = run_pytest(rule_runner, tgt, extra_args=["--pytest-execution-slot-var=SLOT"])
    assert result.exit_code == 1
    assert re.search(r"Value of slot is \d+", result.stdout)


def test_extra_env_vars(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/test_extra_env_vars.py": dedent(
                """\
                import os

                def test_args():
                    assert os.getenv("ARG_WITH_VALUE_VAR") == "arg_with_value_var"
                    assert os.getenv("ARG_WITHOUT_VALUE_VAR") == "arg_without_value_value"
                    assert os.getenv("PYTHON_TESTS_VAR_WITH_VALUE") == "python_tests_var_with_value"
                    assert os.getenv("PYTHON_TESTS_VAR_WITHOUT_VALUE") == "python_tests_var_without_value"
                    assert os.getenv("PYTHON_TESTS_OVERRIDE_WITH_VALUE_VAR") == "python_tests_override_with_value_var_override"
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
            python_tests(
                extra_env_vars=(
                    "PYTHON_TESTS_VAR_WITHOUT_VALUE",
                    "PYTHON_TESTS_VAR_WITH_VALUE=python_tests_var_with_value",
                    "PYTHON_TESTS_OVERRIDE_WITH_VALUE_VAR=python_tests_override_with_value_var_override",
                )
            )
            """
            ),
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="test_extra_env_vars.py"))
    result = run_pytest(
        rule_runner,
        tgt,
        extra_args=[
            '--test-extra-env-vars=["ARG_WITH_VALUE_VAR=arg_with_value_var", "ARG_WITHOUT_VALUE_VAR", "PYTHON_TESTS_OVERRIDE_ARG_WITH_VALUE_VAR"]'
        ],
        env={
            "ARG_WITHOUT_VALUE_VAR": "arg_without_value_value",
            "PYTHON_TESTS_VAR_WITHOUT_VALUE": "python_tests_var_without_value",
            "PYTHON_TESTS_OVERRIDE_WITH_VALUE_VAR": "python_tests_override_with_value_var",
        },
    )
    assert result.exit_code == 0


class UsedPlugin(PytestPluginSetupRequest):
    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        return True


class UnusedPlugin(PytestPluginSetupRequest):
    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        return False


@rule
async def used_plugin(_: UsedPlugin) -> PytestPluginSetup:
    digest = await Get(Digest, CreateDigest([FileContent("used.txt", b"")]))
    return PytestPluginSetup(digest=digest)


@rule
async def unused_plugin(_: UnusedPlugin) -> PytestPluginSetup:
    digest = await Get(Digest, CreateDigest([FileContent("unused.txt", b"")]))
    return PytestPluginSetup(digest=digest)


def test_setup_plugins_and_runtime_package_dependency(rule_runner: RuleRunner) -> None:
    # We test both the generic `PytestPluginSetup` mechanism and our `runtime_package_dependencies`
    # feature in the same test to confirm multiple plugins can be used on the same target.
    rule_runner = RuleRunner(
        rules=[
            *rule_runner.rules,
            used_plugin,
            unused_plugin,
            UnionRule(PytestPluginSetupRequest, UsedPlugin),
            UnionRule(PytestPluginSetupRequest, UnusedPlugin),
        ],
        target_types=rule_runner.target_types,
    )
    rule_runner.write_files(
        {
            f"{PACKAGE}/say_hello.py": "print('Hello, test!')",
            f"{PACKAGE}/test_binary_call.py": dedent(
                f"""\
                import os.path
                import subprocess

                def test_embedded_binary():
                    assert os.path.exists("bin.pex")
                    assert b"Hello, test!" in subprocess.check_output(args=['./bin.pex'])

                    # Ensure that we didn't accidentally pull in the binary's sources. This is a
                    # special type of dependency that should not be included with the rest of the
                    # normal dependencies.
                    assert not os.path.exists("{PACKAGE}/say_hello.py")

                def test_additional_plugins():
                    assert os.path.exists("used.txt")
                    assert not os.path.exists("unused.txt")
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_sources(name='bin_lib', sources=['say_hello.py'])
                pex_binary(name='bin', entry_point='say_hello.py', output_path="bin.pex")
                python_tests(runtime_package_dependencies=[':bin'])
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="test_binary_call.py"))
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0


def test_local_dists(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/foo/bar.py": "BAR = 'LOCAL DIST'",
            f"{PACKAGE}/foo/setup.py": dedent(
                """\
                from setuptools import setup

                setup(name="foo", version="9.8.7", packages=["foo"], package_dir={"foo": "."},)
                """
            ),
            f"{PACKAGE}/foo/bar_test.py": dedent(
                """
                from foo.bar import BAR

                def test_bar():
                  assert BAR == "LOCAL DIST"
                """
            ),
            f"{PACKAGE}/foo/BUILD": dedent(
                """\
                python_sources(name="lib")

                python_distribution(
                    name="dist",
                    dependencies=[":lib"],
                    provides=python_artifact(name="foo", version="9.8.7"),
                    sdist=False,
                    generate_setup=False,
                )

                # Force-exclude any dep on bar.py, so the only way to consume it is via the dist.
                python_tests(name="tests", sources=["bar_test.py"],
                             dependencies=[":dist", "!!:lib"])
                """
            ),
        }
    )
    tgt = rule_runner.get_target(
        Address(os.path.join(PACKAGE, "foo"), target_name="tests", relative_file_path="bar_test.py")
    )
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0


def test_skip_tests(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test_skip_me.py": "",
            "test_foo.py": "",
            "BUILD": dedent(
                """\
                python_tests(name='t1', sources=['test_skip_me.py'], skip_tests=True)
                python_tests(name='t2', sources=['test_foo.py'])
                """
            ),
        }
    )

    def is_applicable(tgt_name: str, fp: str) -> bool:
        tgt = rule_runner.get_target(Address("", target_name=tgt_name, relative_file_path=fp))
        return PythonTestFieldSet.is_applicable(tgt)

    assert not is_applicable("t1", "test_skip_me.py")
    assert is_applicable("t2", "test_foo.py")
