# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from pathlib import PurePath
from textwrap import dedent
from typing import List, Mapping, Optional

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals import package_pex_binary, pytest_runner
from pants.backend.python.goals.coverage_py import create_coverage_config
from pants.backend.python.goals.pytest_runner import PythonTestFieldSet
from pants.backend.python.target_types import (
    PexBinary,
    PythonLibrary,
    PythonRequirementLibrary,
    PythonTests,
)
from pants.backend.python.util_rules import pex_from_targets
from pants.core.goals.test import TestDebugRequest, TestResult, get_filtered_environment
from pants.core.util_rules import distdir
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents, FileContent
from pants.engine.process import InteractiveRunner
from pants.testutil.python_interpreter_selection import skip_unless_python27_and_python3_present
from pants.testutil.rule_runner import QueryRule, RuleRunner, mock_console


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            create_coverage_config,
            *pytest_runner.rules(),
            *pex_from_targets.rules(),
            *dependency_inference_rules.rules(),  # For conftest detection.
            *distdir.rules(),
            *package_pex_binary.rules(),
            get_filtered_environment,
            *target_types_rules.rules(),
            QueryRule(TestResult, (PythonTestFieldSet,)),
            QueryRule(TestDebugRequest, (PythonTestFieldSet,)),
        ],
        target_types=[PexBinary, PythonLibrary, PythonTests, PythonRequirementLibrary],
    )


SOURCE_ROOT = "tests/python"
PACKAGE = os.path.join(SOURCE_ROOT, "pants_test")
GOOD_SOURCE = FileContent(f"{PACKAGE}/test_good.py", b"def test():\n  pass\n")
GOOD_WITH_PRINT = FileContent(f"{PACKAGE}/test_good.py", b"def test():\n  print('All good!')")
BAD_SOURCE = FileContent(f"{PACKAGE}/test_bad.py", b"def test():\n  assert False\n")
PY3_ONLY_SOURCE = FileContent(f"{PACKAGE}/test_py3.py", b"def test() -> None:\n  pass\n")
LIBRARY_SOURCE = FileContent(f"{PACKAGE}/library.py", b"def add_two(x):\n  return x + 2\n")
BINARY_SOURCE = FileContent(f"{PACKAGE}/say_hello.py", b"print('Hello, test!')")


def create_python_library(
    rule_runner: RuleRunner,
    source_files: List[FileContent],
    *,
    name: str = "library",
    dependencies: Optional[List[str]] = None,
) -> None:
    for source_file in source_files:
        rule_runner.create_file(source_file.path, source_file.content.decode())
    source_globs = [PurePath(source_file.path).name for source_file in source_files]
    rule_runner.add_to_build_file(
        PACKAGE,
        dedent(
            f"""\
            python_library(
                name={repr(name)},
                sources={source_globs},
                dependencies={[*(dependencies or ())]},
            )
            """
        ),
    )
    rule_runner.create_file(os.path.join(PACKAGE, "__init__.py"))


def create_test_target(
    rule_runner: RuleRunner,
    source_files: List[FileContent],
    *,
    name: str = "tests",
    dependencies: Optional[List[str]] = None,
    interpreter_constraints: Optional[str] = None,
) -> PythonTests:
    for source_file in source_files:
        rule_runner.create_file(source_file.path, source_file.content.decode())
    rule_runner.add_to_build_file(
        relpath=PACKAGE,
        target=dedent(
            f"""\
            python_tests(
              name={repr(name)},
              dependencies={dependencies or []},
              interpreter_constraints={[interpreter_constraints] if interpreter_constraints else []},
            )
            """
        ),
    )
    tgt = rule_runner.get_target(Address(PACKAGE, target_name=name))
    assert isinstance(tgt, PythonTests)
    return tgt


def create_pex_binary_target(rule_runner: RuleRunner, source_file: FileContent) -> None:
    rule_runner.create_file(source_file.path, source_file.content.decode())
    file_name = PurePath(source_file.path).name
    rule_runner.add_to_build_file(
        relpath=PACKAGE,
        target=dedent(
            f"""\
            python_library(name='bin_lib', sources=['{file_name}'])
            pex_binary(name='bin', entry_point='{file_name}', output_path="bin.pex")
            """
        ),
    )


def setup_thirdparty_dep(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        relpath="3rdparty/python",
        target=(
            "python_requirement_library(name='ordered-set', requirements=['ordered-set==3.1.1'])"
        ),
    )


def run_pytest(
    rule_runner: RuleRunner,
    test_target: PythonTests,
    *,
    passthrough_args: Optional[str] = None,
    junit_xml_dir: Optional[str] = None,
    use_coverage: bool = False,
    execution_slot_var: Optional[str] = None,
    extra_env_vars: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    config: Optional[str] = None,
    force: bool = False,
) -> TestResult:
    args = [
        "--backend-packages=pants.backend.python",
        f"--source-root-patterns={SOURCE_ROOT}",
        # pin to lower versions so that we can run Python 2 tests
        "--pytest-version=pytest>=4.6.6,<4.7",
        "--pytest-pytest-plugins=['zipp==1.0.0', 'pytest-cov>=2.8.1,<2.9']",
    ]
    if passthrough_args:
        args.append(f"--pytest-args='{passthrough_args}'")
    if extra_env_vars:
        args.append(f"--test-extra-env-vars={extra_env_vars}")
    if junit_xml_dir:
        args.append(f"--pytest-junit-xml-dir={junit_xml_dir}")
    if use_coverage:
        args.append("--test-use-coverage")
    if execution_slot_var:
        args.append(f"--pytest-execution-slot-var={execution_slot_var}")
    if config:
        rule_runner.create_file(relpath="pytest.ini", contents=config)
        args.append("--pytest-config=pytest.ini")
    if force:
        args.append("--test-force")
    rule_runner.set_options(args, env=env)

    inputs = [PythonTestFieldSet.create(test_target)]
    test_result = rule_runner.request(TestResult, inputs)
    debug_request = rule_runner.request(TestDebugRequest, inputs)
    if debug_request.process is not None:
        with mock_console(rule_runner.options_bootstrapper):
            debug_result = InteractiveRunner(rule_runner.scheduler).run(debug_request.process)
            assert test_result.exit_code == debug_result.exit_code
    return test_result


def test_single_passing_test(rule_runner: RuleRunner) -> None:
    tgt = create_test_target(rule_runner, [GOOD_SOURCE])
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_good.py ." in result.stdout


def test_force(rule_runner: RuleRunner) -> None:
    tgt = create_test_target(rule_runner, [GOOD_SOURCE])

    # Should not receive a memoized result if force=True.
    result_one = run_pytest(rule_runner, tgt, force=True)
    result_two = run_pytest(rule_runner, tgt, force=True)
    assert result_one.exit_code == 0
    assert result_two.exit_code == 0
    assert result_one is not result_two

    # But should if force=False.
    result_one = run_pytest(rule_runner, tgt, force=False)
    result_two = run_pytest(rule_runner, tgt, force=False)
    assert result_one.exit_code == 0
    assert result_one is result_two


def test_single_failing_test(rule_runner: RuleRunner) -> None:
    tgt = create_test_target(rule_runner, [BAD_SOURCE])
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 1
    assert f"{PACKAGE}/test_bad.py F" in result.stdout


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    tgt = create_test_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 1
    assert f"{PACKAGE}/test_good.py ." in result.stdout
    assert f"{PACKAGE}/test_bad.py F" in result.stdout


def test_absolute_import(rule_runner: RuleRunner) -> None:
    create_python_library(rule_runner, [LIBRARY_SOURCE])
    source = FileContent(
        path=f"{PACKAGE}/test_absolute_import.py",
        content=dedent(
            """\
            from pants_test.library import add_two

            def test():
              assert add_two(2) == 4
            """
        ).encode(),
    )
    tgt = create_test_target(rule_runner, [source], dependencies=[":library"])
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_absolute_import.py ." in result.stdout


def test_relative_import(rule_runner: RuleRunner) -> None:
    create_python_library(rule_runner, [LIBRARY_SOURCE])
    source = FileContent(
        path=f"{PACKAGE}/test_relative_import.py",
        content=dedent(
            """\
            from .library import add_two

            def test():
              assert add_two(2) == 4
            """
        ).encode(),
    )
    tgt = create_test_target(rule_runner, [source], dependencies=[":library"])
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_relative_import.py ." in result.stdout


def test_respects_config(rule_runner: RuleRunner) -> None:
    target = create_test_target(rule_runner, [GOOD_WITH_PRINT])
    result = run_pytest(rule_runner, target, config="[pytest]\naddopts = -s\n")
    assert result.exit_code == 0
    assert "All good!" in result.stdout and "Captured" not in result.stdout


def test_transitive_dep(rule_runner: RuleRunner) -> None:
    create_python_library(rule_runner, [LIBRARY_SOURCE])
    transitive_dep_fc = FileContent(
        path=f"{PACKAGE}/transitive_dep.py",
        content=dedent(
            """\
            from pants_test.library import add_two

            def add_four(x):
              return add_two(x) + 2
            """
        ).encode(),
    )
    create_python_library(
        rule_runner, [transitive_dep_fc], name="transitive_dep", dependencies=[":library"]
    )
    source = FileContent(
        path=f"{PACKAGE}/test_transitive_dep.py",
        content=dedent(
            """\
            from pants_test.transitive_dep import add_four

            def test():
              assert add_four(2) == 6
            """
        ).encode(),
    )
    tgt = create_test_target(rule_runner, [source], dependencies=[":transitive_dep"])
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_transitive_dep.py ." in result.stdout


def test_thirdparty_dep(rule_runner: RuleRunner) -> None:
    setup_thirdparty_dep(rule_runner)
    source = FileContent(
        path=f"{PACKAGE}/test_3rdparty_dep.py",
        content=dedent(
            """\
            from ordered_set import OrderedSet

            def test():
              assert OrderedSet((1, 2)) == OrderedSet([1, 2])
            """
        ).encode(),
    )
    tgt = create_test_target(rule_runner, [source], dependencies=["3rdparty/python:ordered-set"])
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_3rdparty_dep.py ." in result.stdout


def test_thirdparty_transitive_dep(rule_runner: RuleRunner) -> None:
    setup_thirdparty_dep(rule_runner)
    library_fc = FileContent(
        path=f"{PACKAGE}/library.py",
        content=dedent(
            """\
            import string
            from ordered_set import OrderedSet

            alphabet = OrderedSet(string.ascii_lowercase)
            """
        ).encode(),
    )
    create_python_library(
        rule_runner,
        [library_fc],
        dependencies=["3rdparty/python:ordered-set"],
    )
    source = FileContent(
        path=f"{PACKAGE}/test_3rdparty_transitive_dep.py",
        content=dedent(
            """\
            from pants_test.library import alphabet

            def test():
              assert 'a' in alphabet and 'z' in alphabet
            """
        ).encode(),
    )
    tgt = create_test_target(rule_runner, [source], dependencies=[":library"])
    result = run_pytest(rule_runner, tgt)
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_3rdparty_transitive_dep.py ." in result.stdout


@skip_unless_python27_and_python3_present
def test_uses_correct_python_version(rule_runner: RuleRunner) -> None:
    tgt = create_test_target(
        rule_runner, [PY3_ONLY_SOURCE], name="py2", interpreter_constraints="CPython==2.7.*"
    )
    py2_result = run_pytest(rule_runner, tgt)
    assert py2_result.exit_code == 2
    assert "SyntaxError: invalid syntax" in py2_result.stdout

    tgt = create_test_target(
        rule_runner, [PY3_ONLY_SOURCE], name="py3", interpreter_constraints="CPython>=3.6"
    )
    py3_result = run_pytest(rule_runner, tgt)
    assert py3_result.exit_code == 0
    assert f"{PACKAGE}/test_py3.py ." in py3_result.stdout


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    source = FileContent(
        path=f"{PACKAGE}/test_config.py",
        content=dedent(
            """\
            def test_run_me():
              pass

            def test_ignore_me():
              pass
            """
        ).encode(),
    )
    tgt = create_test_target(rule_runner, [source])
    result = run_pytest(rule_runner, tgt, passthrough_args="-k test_run_me")
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_config.py ." in result.stdout
    assert "collected 2 items / 1 deselected / 1 selected" in result.stdout


def test_junit(rule_runner: RuleRunner) -> None:
    tgt = create_test_target(rule_runner, [GOOD_SOURCE])
    result = run_pytest(rule_runner, tgt, junit_xml_dir="dist/test-results")
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_good.py ." in result.stdout
    assert result.xml_results is not None
    digest_contents = rule_runner.request(DigestContents, [result.xml_results.digest])
    file = digest_contents[0]
    assert file.path.startswith("dist/test-results")
    assert b"pants_test.test_good" in file.content


def test_coverage(rule_runner: RuleRunner) -> None:
    tgt = create_test_target(rule_runner, [GOOD_SOURCE])
    result = run_pytest(rule_runner, tgt, use_coverage=True)
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_good.py ." in result.stdout
    assert result.coverage_data is not None


def test_conftest_handling(rule_runner: RuleRunner) -> None:
    """Tests that we a) inject a dependency on conftest.py and b) skip running directly on
    conftest.py."""
    tgt = create_test_target(rule_runner, [GOOD_SOURCE])

    rule_runner.create_file(
        f"{SOURCE_ROOT}/conftest.py", "def pytest_runtest_setup(item):\n  print('In conftest!')\n"
    )
    rule_runner.add_to_build_file(SOURCE_ROOT, "python_tests()")
    conftest_tgt = rule_runner.get_target(Address(SOURCE_ROOT, relative_file_path="conftest.py"))
    assert isinstance(conftest_tgt, PythonTests)

    result = run_pytest(rule_runner, tgt, passthrough_args="-s")
    assert result.exit_code == 0
    assert f"{PACKAGE}/test_good.py In conftest!\n." in result.stdout

    result = run_pytest(rule_runner, conftest_tgt)
    assert result.exit_code is None


def test_execution_slot_variable(rule_runner: RuleRunner) -> None:
    source = FileContent(
        path=f"{PACKAGE}/test_concurrency_slot.py",
        content=dedent(
            """\
            import os

            def test_fail_printing_slot_env_var():
                slot = os.getenv("SLOT")
                print(f"Value of slot is {slot}")
                # Deliberately fail the test so the SLOT output gets printed to stdout
                assert 1 == 2
            """
        ).encode(),
    )
    tgt = create_test_target(rule_runner, [source])
    result = run_pytest(rule_runner, tgt, execution_slot_var="SLOT")
    assert result.exit_code == 1
    assert re.search(r"Value of slot is \d+", result.stdout)


def test_extra_env_vars(rule_runner: RuleRunner) -> None:
    source = FileContent(
        path=f"{PACKAGE}/test_extra_env_vars.py",
        content=dedent(
            """\
            import os

            def test_args():
                assert os.getenv("SOME_VAR") == "some_value"
                assert os.getenv("OTHER_VAR") == "other_value"
            """
        ).encode(),
    )
    tgt = create_test_target(rule_runner, [source])
    result = run_pytest(
        rule_runner,
        tgt,
        extra_env_vars='["SOME_VAR=some_value", "OTHER_VAR"]',
        env={"OTHER_VAR": "other_value"},
    )
    assert result.exit_code == 0


def test_runtime_package_dependency(rule_runner: RuleRunner) -> None:
    create_pex_binary_target(rule_runner, BINARY_SOURCE)
    rule_runner.create_file(
        f"{PACKAGE}/test_binary_call.py",
        dedent(
            f"""\
            import os.path
            import subprocess

            def test_embedded_binary():
                assert  b"Hello, test!" in subprocess.check_output(args=['./bin.pex'])

                # Ensure that we didn't accidentally pull in the binary's sources. This is a
                # special type of dependency that should not be included with the rest of the
                # normal dependencies.
                assert os.path.exists("{BINARY_SOURCE.path}") is False
            """
        ),
    )
    rule_runner.add_to_build_file(PACKAGE, "python_tests(runtime_package_dependencies=[':bin'])")
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="test_binary_call.py"))
    assert isinstance(tgt, PythonTests)
    result = run_pytest(rule_runner, tgt, passthrough_args="-s")
    assert result.exit_code == 0


def test_skip_type_stubs(rule_runner: RuleRunner) -> None:
    rule_runner.create_file(f"{PACKAGE}/test_foo.pyi", "def test_foo() -> None:\n    ...\n")
    rule_runner.add_to_build_file(PACKAGE, "python_tests()")
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="test_foo.pyi"))
    assert isinstance(tgt, PythonTests)

    result = run_pytest(rule_runner, tgt)
    assert result.exit_code is None
