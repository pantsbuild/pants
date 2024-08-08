# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
import unittest.mock
from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals import package_dists, package_pex_binary, pytest_runner
from pants.backend.python.goals.coverage_py import create_or_update_coverage_config
from pants.backend.python.goals.pytest_runner import (
    PytestPluginSetup,
    PytestPluginSetupRequest,
    PyTestRequest,
    TestMetadata,
)
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.pytest import PythonTestFieldSet
from pants.backend.python.target_types import (
    PexBinary,
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonTestsGeneratorTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.backend.python.util_rules import local_dists, pex_from_targets
from pants.core.goals import package
from pants.core.goals.test import (
    TestDebugAdapterRequest,
    TestDebugRequest,
    TestResult,
    build_runtime_package_dependencies,
    get_filtered_environment,
)
from pants.core.util_rules import config_files, distdir
from pants.core.util_rules.partitions import Partitions
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent
from pants.engine.process import InteractiveProcessResult
from pants.engine.rules import Get, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.testutil.debug_adapter_util import debugadapter_port_for_testing
from pants.testutil.python_interpreter_selection import (
    all_major_minor_python_versions,
    skip_unless_python37_and_python39_present,
)
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule, mock_console
from pants.util.resources import read_sibling_resource


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            build_runtime_package_dependencies,
            create_or_update_coverage_config,
            *pytest_runner.rules(),
            *pex_from_targets.rules(),
            *dependency_inference_rules.rules(),
            *distdir.rules(),
            *config_files.rules(),
            *package_pex_binary.rules(),
            get_filtered_environment,
            *target_types_rules.rules(),
            *local_dists.rules(),
            *package_dists.rules(),
            *package.rules(),
            QueryRule(Partitions, (PyTestRequest.PartitionRequest,)),
            QueryRule(TestResult, (PyTestRequest.Batch,)),
            QueryRule(TestDebugRequest, (PyTestRequest.Batch,)),
            QueryRule(TestDebugAdapterRequest, (PyTestRequest.Batch,)),
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


def _configure_pytest_runner(
    rule_runner: PythonRuleRunner,
    *,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    args = [
        "--backend-packages=pants.backend.python",
        f"--source-root-patterns={SOURCE_ROOT}",
        f"--debug-adapter-port={debugadapter_port_for_testing()}",
        *(extra_args or ()),
    ]
    rule_runner.set_options(args, env=env, env_inherit={"PATH", "PYENV_ROOT", "HOME"})


def _get_pytest_batch(
    rule_runner: PythonRuleRunner, test_targets: Iterable[Target]
) -> PyTestRequest.Batch[PythonTestFieldSet, TestMetadata]:
    field_sets = tuple(PythonTestFieldSet.create(tgt) for tgt in test_targets)
    partitions = rule_runner.request(Partitions, [PyTestRequest.PartitionRequest(field_sets)])
    assert len(partitions) == 1
    return PyTestRequest.Batch("", partitions[0].elements, partitions[0].metadata)


def run_pytest(
    rule_runner: PythonRuleRunner,
    test_targets: Iterable[Target],
    *,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
    test_debug_adapter: bool = True,
) -> TestResult:
    _configure_pytest_runner(rule_runner, extra_args=extra_args, env=env)
    batch = _get_pytest_batch(rule_runner, test_targets)
    test_result = rule_runner.request(TestResult, [batch])
    debug_request = rule_runner.request(TestDebugRequest, [batch])
    if debug_request.process is not None:
        with mock_console(rule_runner.options_bootstrapper):
            debug_result = rule_runner.run_interactive_process(debug_request.process)
            assert test_result.exit_code == debug_result.exit_code

    if test_debug_adapter:
        debug_adapter_request = rule_runner.request(TestDebugAdapterRequest, [batch])
        if debug_adapter_request.process is not None:
            with mock_console(rule_runner.options_bootstrapper) as mocked_console:
                _, stdioreader = mocked_console
                debug_adapter_result = rule_runner.run_interactive_process(
                    debug_adapter_request.process
                )
                assert (
                    test_result.exit_code == debug_adapter_result.exit_code
                ), f"{stdioreader.get_stdout()}\n{stdioreader.get_stderr()}"

    return test_result


def run_pytest_noninteractive(
    rule_runner: PythonRuleRunner,
    test_target: Target,
    *,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> TestResult:
    _configure_pytest_runner(rule_runner, extra_args=extra_args, env=env)
    return rule_runner.request(TestResult, [_get_pytest_batch(rule_runner, [test_target])])


def run_pytest_interactive(
    rule_runner: PythonRuleRunner,
    test_target: Target,
    *,
    extra_args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> InteractiveProcessResult:
    _configure_pytest_runner(rule_runner, extra_args=extra_args, env=env)
    debug_request = rule_runner.request(
        TestDebugRequest, [_get_pytest_batch(rule_runner, [test_target])]
    )
    with mock_console(rule_runner.options_bootstrapper):
        return rule_runner.run_interactive_process(debug_request.process)


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(["CPython>=3.7,<4"]),
)
def test_passing(rule_runner: PythonRuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files(
        {f"{PACKAGE}/tests.py": GOOD_TEST, f"{PACKAGE}/BUILD": "python_tests()"}
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(
        rule_runner,
        [tgt],
        extra_args=[f"--python-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert result.xml_results is not None
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout_simplified_str


def test_failing(rule_runner: PythonRuleRunner) -> None:
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
    result = run_pytest(rule_runner, [tgt])
    assert result.exit_code == 1
    assert f"{PACKAGE}/tests.py F" in result.stdout_simplified_str


def test_dependencies(rule_runner: PythonRuleRunner) -> None:
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
    result = run_pytest(rule_runner, [tgt])
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout_simplified_str


@skip_unless_python37_and_python39_present
def test_uses_correct_python_version(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/tests.py": dedent(
                """\
                def test() -> None:
                  y = (x := 5)
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_tests(name='py37', interpreter_constraints=['==3.7.*'])
                python_tests(name='py39', interpreter_constraints=['==3.9.*'])
                """
            ),
        }
    )

    py37_tgt = rule_runner.get_target(
        Address(PACKAGE, target_name="py37", relative_file_path="tests.py")
    )
    result = run_pytest(rule_runner, [py37_tgt], test_debug_adapter=False)
    assert result.exit_code == 2
    assert b"SyntaxError: invalid syntax" in result.stdout_bytes

    py39_tgt = rule_runner.get_target(
        Address(PACKAGE, target_name="py39", relative_file_path="tests.py")
    )
    result = run_pytest(rule_runner, [py39_tgt], test_debug_adapter=False)
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout_simplified_str


def test_passthrough_args(rule_runner: PythonRuleRunner) -> None:
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
    result = run_pytest(rule_runner, [tgt], extra_args=["--pytest-args='-k test_run_me'"])
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout_simplified_str
    assert b"collected 2 items / 1 deselected / 1 selected" in result.stdout_bytes


def test_xdist_enabled_noninteractive(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/tests.py": dedent(
                """\
                import os

                def test_worker_id_set():
                  assert "PYTEST_XDIST_WORKER" in os.environ

                def test_worker_count_set():
                  assert "PYTEST_XDIST_WORKER_COUNT" in os.environ
                """
            ),
            f"{PACKAGE}/BUILD": "python_tests(xdist_concurrency=2)",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest_noninteractive(rule_runner, tgt, extra_args=["--pytest-xdist-enabled"])
    assert result.exit_code == 0


def test_xdist_enabled_but_disabled_for_target(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/tests.py": dedent(
                """\
                import os

                def test_worker_id_not_set():
                  assert "PYTEST_XDIST_WORKER" not in os.environ

                def test_worker_count_not_set():
                  assert "PYTEST_XDIST_WORKER_COUNT" not in os.environ
                """
            ),
            f"{PACKAGE}/BUILD": "python_tests(xdist_concurrency=0)",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest_noninteractive(rule_runner, tgt, extra_args=["--pytest-xdist-enabled"])
    assert result.exit_code == 0


def test_xdist_enabled_interactive(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/tests.py": dedent(
                """\
                import os

                def test_worker_id_not_set():
                  assert "PYTEST_XDIST_WORKER" not in os.environ

                def test_worker_count_not_set():
                  assert "PYTEST_XDIST_WORKER_COUNT" not in os.environ
                """
            ),
            f"{PACKAGE}/BUILD": "python_tests(xdist_concurrency=2)",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest_interactive(rule_runner, tgt, extra_args=["--pytest-xdist-enabled"])
    assert result.exit_code == 0


@pytest.mark.parametrize(
    "config_path,extra_args",
    (["pytest.ini", []], ["custom_config.ini", ["--pytest-config=custom_config.ini"]]),
)
def test_config_file(
    rule_runner: PythonRuleRunner, config_path: str, extra_args: list[str]
) -> None:
    rule_runner.write_files(
        {
            config_path: dedent(
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
    result = run_pytest(rule_runner, [tgt], extra_args=extra_args)
    assert result.exit_code == 0
    assert b"All good!" in result.stdout_bytes and b"Captured" not in result.stdout_bytes


def test_force(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {f"{PACKAGE}/tests.py": GOOD_TEST, f"{PACKAGE}/BUILD": "python_tests()"}
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))

    # Should not receive a memoized result if force=True.
    result_one = run_pytest(rule_runner, [tgt], extra_args=["--test-force"])
    result_two = run_pytest(rule_runner, [tgt], extra_args=["--test-force"])
    assert result_one.exit_code == 0
    assert result_two.exit_code == 0
    assert result_one is not result_two

    # But should if force=False.
    result_one = run_pytest(rule_runner, [tgt])
    result_two = run_pytest(rule_runner, [tgt])
    assert result_one.exit_code == 0
    assert result_one is result_two


def test_extra_output(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/tests.py": GOOD_TEST,
            f"{PACKAGE}/BUILD": "python_tests()",
            # The test lockfile provides pytest-html and also setuptools, which it requires
            # because it does not use PEP 517.
            "pytest.lock": read_sibling_resource(__name__, "pytest_extra_output_test.lock"),
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="tests.py"))
    result = run_pytest(
        rule_runner,
        [tgt],
        extra_args=[
            "--pytest-args='--html=extra-output/report.html'",
            "--python-resolves={'pytest':'pytest.lock'}",
            "--pytest-install-from-resolve=pytest",
        ],
    )
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout_simplified_str
    assert result.extra_output is not None
    digest_contents = rule_runner.request(DigestContents, [result.extra_output.digest])
    paths = {dc.path for dc in digest_contents}
    assert {"assets/style.css", "report.html"} == paths


def test_coverage(rule_runner: PythonRuleRunner) -> None:
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
    result = run_pytest(rule_runner, [tgt], extra_args=["--test-use-coverage"])
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py ." in result.stdout_simplified_str
    assert result.coverage_data is not None


def test_conftest_dependency_injection(rule_runner: PythonRuleRunner) -> None:
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
    result = run_pytest(rule_runner, [tgt], extra_args=["--pytest-args='-s'"])
    assert result.exit_code == 0
    assert f"{PACKAGE}/tests.py In conftest!\n." in result.stdout_simplified_str


def test_execution_slot_variable(rule_runner: PythonRuleRunner) -> None:
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
    result = run_pytest(rule_runner, [tgt], extra_args=["--pytest-execution-slot-var=SLOT"])
    assert result.exit_code == 1
    assert re.search(r"Value of slot is \d+", result.stdout_simplified_str)


def test_extra_env_vars(rule_runner: PythonRuleRunner) -> None:
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
        [tgt],
        extra_args=[
            "--test-extra-env-vars=['ARG_WITH_VALUE_VAR=arg_with_value_var', 'ARG_WITHOUT_VALUE_VAR', 'PYTHON_TESTS_OVERRIDE_ARG_WITH_VALUE_VAR']"
        ],
        env={
            "ARG_WITHOUT_VALUE_VAR": "arg_without_value_value",
            "PYTHON_TESTS_VAR_WITHOUT_VALUE": "python_tests_var_without_value",
            "PYTHON_TESTS_OVERRIDE_WITH_VALUE_VAR": "python_tests_override_with_value_var",
        },
    )
    assert result.exit_code == 0


def test_pytest_addopts_test_extra_env(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/test_pytest_addopts_test_extra_env.py": dedent(
                """\
                import os

                def test_addopts():
                    assert "-vv" in os.getenv("PYTEST_ADDOPTS")
                    assert "--maxfail=2" in os.getenv("PYTEST_ADDOPTS")
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_tests()
                """
            ),
        }
    )
    tgt = rule_runner.get_target(
        Address(PACKAGE, relative_file_path="test_pytest_addopts_test_extra_env.py")
    )
    result = run_pytest(
        rule_runner,
        [tgt],
        extra_args=[
            "--test-extra-env-vars=['PYTEST_ADDOPTS=-vv --maxfail=2']",
        ],
    )
    assert result.exit_code == 0


def test_pytest_addopts_field_set_extra_env(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/test_pytest_addopts_field_set_extra_env.py": dedent(
                """\
                import os

                def test_addopts():
                    assert "-vv" not in os.getenv("PYTEST_ADDOPTS")
                    assert "--maxfail=2" not in os.getenv("PYTEST_ADDOPTS")
                    assert "-ra" in os.getenv("PYTEST_ADDOPTS")
                    assert "-q" in os.getenv("PYTEST_ADDOPTS")
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_tests(
                    extra_env_vars=(
                        "PYTEST_ADDOPTS=-ra -q",
                    )
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(
        Address(PACKAGE, relative_file_path="test_pytest_addopts_field_set_extra_env.py")
    )
    result = run_pytest(
        rule_runner,
        [tgt],
        extra_args=[
            "--test-extra-env-vars=['PYTEST_ADDOPTS=-vv --maxfail=2']",  # should be overridden by `python_tests`
        ],
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
    return PytestPluginSetup(digest=digest, extra_sys_path=("sys/path/used",))


@rule
async def unused_plugin(_: UnusedPlugin) -> PytestPluginSetup:
    digest = await Get(Digest, CreateDigest([FileContent("unused.txt", b"")]))
    return PytestPluginSetup(digest=digest, extra_sys_path=("sys/path/unused",))


def test_setup_plugins_and_runtime_package_dependency(rule_runner: PythonRuleRunner) -> None:
    # We test both the generic `PytestPluginSetup` mechanism and our `runtime_package_dependencies`
    # feature in the same test to confirm multiple plugins can be used on the same target.
    rule_runner = PythonRuleRunner(
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
                import sys

                def test_embedded_binary():
                    assert os.path.exists("bin.pex")
                    assert b"Hello, test!" in subprocess.check_output(args=['./bin.pex'])

                    # Ensure that we didn't accidentally pull in the binary's sources. This is a
                    # special type of dependency that should not be included with the rest of the
                    # normal dependencies.
                    assert not os.path.exists("{PACKAGE}/say_hello.py")

                def test_additional_plugins_digest():
                    assert os.path.exists("used.txt")
                    assert not os.path.exists("unused.txt")

                def test_additional_plugins_extra_sys_path():
                    assert "sys/path/used" in sys.path
                    assert "sys/path/unused" not in sys.path
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
    result = run_pytest(rule_runner, [tgt])
    assert result.exit_code == 0, f"pytest test faied:\n{result.stdout_bytes.decode()}"


def test_local_dists(rule_runner: PythonRuleRunner) -> None:
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
    result = run_pytest(rule_runner, [tgt])
    assert result.exit_code == 0


def test_skip_tests(rule_runner: PythonRuleRunner) -> None:
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


def test_debug_adaptor_request_argv(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/test_foo.py": "",
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_tests(name='tests')
                """
            ),
        }
    )

    args = [
        "--backend-packages=pants.backend.python",
        f"--source-root-patterns={SOURCE_ROOT}",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    tgt = rule_runner.get_target(
        Address(PACKAGE, target_name="tests", relative_file_path="test_foo.py")
    )
    request = rule_runner.request(TestDebugAdapterRequest, [_get_pytest_batch(rule_runner, [tgt])])
    assert request.process is not None
    assert request.process.process.argv == (
        "./pytest_runner.pex_pex_shim.sh",
        "--listen",
        "127.0.0.1:5678",
        "-c",
        unittest.mock.ANY,
        "--color=yes",
        "tests/python/pants_test/test_foo.py",
    )


@pytest.mark.parametrize(
    "root_build_contents,package_build_contents,expected_partitions",
    (
        # No batching by default:
        [
            "",
            "python_tests()",
            [[f"{PACKAGE}/test_1.py"], [f"{PACKAGE}/test_2.py"], [f"{PACKAGE}/test_3.py"]],
        ],
        # Compatibility at the `python_tests` level:
        [
            "",
            "python_tests(batch_compatibility_tag='default')",
            [[f"{PACKAGE}/test_1.py", f"{PACKAGE}/test_2.py", f"{PACKAGE}/test_3.py"]],
        ],
        # Compatibility at a higher level via `__defaults__`:
        [
            "__defaults__(dict(python_tests=dict(batch_compatibility_tag='default')))",
            "python_tests()",
            [[f"{PACKAGE}/test_1.py", f"{PACKAGE}/test_2.py", f"{PACKAGE}/test_3.py"]],
        ],
        # Overriding compatibility from a higher __defaults__:
        [
            "__defaults__(dict(python_tests=dict(batch_compatibility_tag='default')))",
            "python_tests(overrides={'test_2.py': {'batch_compatibility_tag': 'other'}})",
            [[f"{PACKAGE}/test_1.py", f"{PACKAGE}/test_3.py"], [f"{PACKAGE}/test_2.py"]],
        ],
        # Partition on incompatible BUILD metadata:
        [
            "__defaults__(dict(python_tests=dict(batch_compatibility_tag='default', extra_env_vars=['HOME'])))",
            "python_tests(overrides={'test_2.py': {'extra_env_vars': []}})",
            [[f"{PACKAGE}/test_1.py", f"{PACKAGE}/test_3.py"], [f"{PACKAGE}/test_2.py"]],
        ],
        # Order of extra_env_vars shouldn't affect partitioning:
        [
            "__defaults__(dict(python_tests=dict(batch_compatibility_tag='default', extra_env_vars=['FOO', 'BAR'])))",
            "python_tests(overrides={'test_2.py': {'extra_env_vars': ['BAR', 'FOO']}})",
            [[f"{PACKAGE}/test_1.py", f"{PACKAGE}/test_2.py", f"{PACKAGE}/test_3.py"]],
        ],
        # Partition on different environments:
        [
            "__defaults__(dict(python_tests=dict(batch_compatibility_tag='default')))",
            "python_tests(overrides={'test_2.py': {'environment': 'remote'}})",
            [[f"{PACKAGE}/test_1.py", f"{PACKAGE}/test_3.py"], [f"{PACKAGE}/test_2.py"]],
        ],
    ),
)
def test_partition(
    rule_runner: PythonRuleRunner,
    root_build_contents: str,
    package_build_contents: str,
    expected_partitions: list[list[str]],
) -> None:
    _configure_pytest_runner(rule_runner)
    rule_runner.write_files(
        {
            "BUILD": root_build_contents,
            f"{PACKAGE}/test_1.py": dedent(
                """\
                def test():
                    assert 1 == 1
                """
            ),
            f"{PACKAGE}/test_2.py": dedent(
                """\
                def test():
                    assert 2 == 2
                """
            ),
            f"{PACKAGE}/test_3.py": dedent(
                """\
                def test():
                    assert 3 == 3
                """
            ),
            f"{PACKAGE}/BUILD": package_build_contents,
        }
    )

    field_sets = tuple(
        PythonTestFieldSet.create(rule_runner.get_target(Address(PACKAGE, relative_file_path=path)))
        for path in ("test_1.py", "test_2.py", "test_3.py")
    )

    partitions = rule_runner.request(
        Partitions[PythonTestFieldSet, TestMetadata], [PyTestRequest.PartitionRequest(field_sets)]
    )
    sorted_partitions = sorted(
        sorted(field_set.address.spec for field_set in partition.elements)
        for partition in partitions
    )

    assert sorted_partitions == expected_partitions


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(["CPython>=3.7,<4"]),
)
def test_batched_passing(rule_runner: PythonRuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/test_1.py": GOOD_TEST,
            f"{PACKAGE}/test_2.py": GOOD_TEST,
            f"{PACKAGE}/BUILD": "python_tests(batch_compatibility_tag='default')",
        }
    )
    targets = tuple(
        rule_runner.get_target(Address(PACKAGE, relative_file_path=path))
        for path in ("test_1.py", "test_2.py")
    )
    result = run_pytest(
        rule_runner,
        targets,
        extra_args=[f"--python-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert result.xml_results is not None
    assert result.exit_code == 0
    stdout_text = result.stdout_simplified_str
    assert f"{PACKAGE}/test_1.py ." in stdout_text
    assert f"{PACKAGE}/test_2.py ." in stdout_text


def test_batched_failing(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/test_1.py": GOOD_TEST,
            f"{PACKAGE}/test_2.py": dedent(
                """\
                def test():
                    assert False
                """
            ),
            f"{PACKAGE}/BUILD": "python_tests(batch_compatibility_tag='default')",
        }
    )
    targets = tuple(
        rule_runner.get_target(Address(PACKAGE, relative_file_path=path))
        for path in ("test_1.py", "test_2.py")
    )
    result = run_pytest(rule_runner, targets)
    assert result.exit_code == 1
    stdout_text = result.stdout_simplified_str
    assert f"{PACKAGE}/test_1.py ." in stdout_text
    assert f"{PACKAGE}/test_2.py F" in stdout_text
