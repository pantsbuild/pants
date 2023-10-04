# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    rules as protobuf_subsystem_rules,
)
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import ProtobufSourceTarget
from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.backend.python.typecheck.mypy.rules import (
    MyPyPartition,
    MyPyPartitions,
    MyPyRequest,
    determine_python_files,
)
from pants.backend.python.typecheck.mypy.rules import rules as mypy_rules
from pants.backend.python.typecheck.mypy.subsystem import MyPy, MyPyFieldSet
from pants.backend.python.typecheck.mypy.subsystem import rules as mypy_subystem_rules
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.check import CheckResult, CheckResults
from pants.core.util_rules import config_files
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, DigestContents
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import (
    all_major_minor_python_versions,
    skip_unless_all_pythons_present,
    skip_unless_python27_and_python3_present,
    skip_unless_python27_present,
    skip_unless_python38_present,
    skip_unless_python39_present,
)
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.util.resources import read_sibling_resource


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *mypy_rules(),
            *mypy_subystem_rules(),
            *dependency_inference_rules.rules(),  # Used for import inference.
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(CheckResults, (MyPyRequest,)),
            QueryRule(MyPyPartitions, (MyPyRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonRequirementTarget, PythonSourceTarget],
    )


PACKAGE = "src/py/project"
GOOD_FILE = dedent(
    """\
    def add(x: int, y: int) -> int:
        return x + y

    result = add(3, 3)
    """
)
BAD_FILE = dedent(
    """\
    def add(x: int, y: int) -> int:
        return x + y

    result = add(2.0, 3.0)
    """
)
# This will fail if `--disallow-any-expr` is configured.
NEEDS_CONFIG_FILE = dedent(
    """\
    from typing import Any, cast

    x = cast(Any, "hello")
    """
)


def run_mypy(
    rule_runner: PythonRuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[CheckResult, ...]:
    rule_runner.set_options(extra_args or (), env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    result = rule_runner.request(
        CheckResults, [MyPyRequest(MyPyFieldSet.create(tgt) for tgt in targets)]
    )
    return result.results


def assert_success(
    rule_runner: PythonRuleRunner, target: Target, *, extra_args: list[str] | None = None
) -> None:
    result = run_mypy(rule_runner, [target], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Success: no issues found" in result[0].stdout.strip()
    assert result[0].report == EMPTY_DIGEST


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(MyPy.default_interpreter_constraints),
)
def test_passing(rule_runner: PythonRuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": GOOD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(
        rule_runner,
        tgt,
        extra_args=[f"--mypy-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )


def test_failing(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_mypy(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/f.py:4" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


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
    result = run_mypy(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/good.py" not in result[0].stdout
    assert f"{PACKAGE}/bad.py:4" in result[0].stdout
    assert "checked 2 source files" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


@pytest.mark.parametrize(
    "config_path,extra_args",
    ([".mypy.ini", []], ["custom_config.ini", ["--mypy-config=custom_config.ini"]]),
)
def test_config_file(
    rule_runner: PythonRuleRunner, config_path: str, extra_args: list[str]
) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": NEEDS_CONFIG_FILE,
            f"{PACKAGE}/BUILD": "python_sources()",
            config_path: "[mypy]\ndisallow_any_expr = True\n",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_mypy(rule_runner, [tgt], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/f.py:3" in result[0].stdout


def test_passthrough_args(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {f"{PACKAGE}/f.py": NEEDS_CONFIG_FILE, f"{PACKAGE}/BUILD": "python_sources()"}
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_mypy(rule_runner, [tgt], extra_args=["--mypy-args='--disallow-any-expr'"])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/f.py:3" in result[0].stdout


def test_skip(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_mypy(rule_runner, [tgt], extra_args=["--mypy-skip"])
    assert not result


def test_report_file(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": GOOD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_mypy(rule_runner, [tgt], extra_args=["--mypy-args='--linecount-report=reports'"])
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Success: no issues found" in result[0].stdout.strip()
    report_files = rule_runner.request(DigestContents, [result[0].report])
    assert len(report_files) == 1
    assert "4       4      1      1 f" in report_files[0].content.decode()


def test_thirdparty_dependency(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": (
                "python_requirement(name='more-itertools', requirements=['more-itertools==8.4.0'])"
            ),
            f"{PACKAGE}/f.py": dedent(
                """\
                from more_itertools import flatten

                assert flatten(42) == [4, 2]
                """
            ),
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_mypy(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/f.py:3" in result[0].stdout


def test_thirdparty_plugin(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "mypy.lock": read_sibling_resource(__name__, "mypy_with_django_stubs.lock"),
            f"{PACKAGE}/settings.py": dedent(
                """\
                from django.urls import URLPattern

                DEBUG = True
                DEFAULT_FROM_EMAIL = "webmaster@example.com"
                SECRET_KEY = "not so secret"
                MY_SETTING = URLPattern(pattern="foo", callback=lambda: None)
                """
            ),
            f"{PACKAGE}/app.py": dedent(
                """\
                from django.utils import text

                assert "forty-two" == text.slugify("forty two")
                assert "42" == text.slugify(42)
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_sources()

                python_requirement(
                    name="reqs", requirements=["django==3.2.19", "django-stubs==1.8.0"]
                )
                """
            ),
            "mypy.ini": dedent(
                """\
                [mypy]
                plugins =
                    mypy_django_plugin.main

                [mypy.plugins.django-stubs]
                django_settings_module = project.settings
                """
            ),
        }
    )
    result = run_mypy(
        rule_runner,
        [
            rule_runner.get_target(Address(PACKAGE, relative_file_path="app.py")),
            rule_runner.get_target(Address(PACKAGE, relative_file_path="settings.py")),
        ],
        extra_args=[
            "--python-resolves={'mypy':'mypy.lock'}",
            "--mypy-install-from-resolve=mypy",
        ],
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/app.py:4" in result[0].stdout


def test_transitive_dependencies(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/util/__init__.py": "",
            f"{PACKAGE}/util/lib.py": dedent(
                """\
                def capitalize(v: str) -> str:
                    return v.capitalize()
                """
            ),
            f"{PACKAGE}/util/BUILD": "python_sources()",
            f"{PACKAGE}/math/__init__.py": "",
            f"{PACKAGE}/math/add.py": dedent(
                """\
                from project.util.lib import capitalize

                def add(x: int, y: int) -> str:
                    sum = x + y
                    return capitalize(sum)  # This is the wrong type.
                """
            ),
            f"{PACKAGE}/math/BUILD": "python_sources()",
            f"{PACKAGE}/__init__.py": "",
            f"{PACKAGE}/app.py": dedent(
                """\
                from project.math.add import add

                print(add(2, 4))
                """
            ),
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="app.py"))
    result = run_mypy(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/math/add.py:5" in result[0].stdout


@skip_unless_python27_present
def test_works_with_python27(rule_runner: PythonRuleRunner) -> None:
    """A regression test that we can properly handle Python 2-only third-party dependencies.

    There was a bug that this would cause the runner PEX to fail to execute because it did not have
    Python 3 distributions of the requirements.

    Also note that this Python 2 support should be automatic: Pants will tell MyPy to run with
    `--py2` by detecting its use in interpreter constraints.
    """
    rule_runner.write_files(
        {
            "mypy.lock": read_sibling_resource(__name__, "older_mypy_for_testing.lock"),
            "BUILD": dedent(
                """\
                # Both requirements are a) typed and b) compatible with Py2 and Py3. However, `x690`
                # has a distinct wheel for Py2 vs. Py3, whereas libumi has a universal wheel. We expect
                # both to be usable, even though libumi is not compatible with Py3.

                python_requirement(
                    name="libumi",
                    requirements=["libumi==0.0.2"],
                )

                python_requirement(
                    name="x690",
                    requirements=["x690==0.2.0"],
                )
                """
            ),
            f"{PACKAGE}/f.py": dedent(
                """\
                from libumi import hello_world
                from x690 import types

                print "Blast from the past!"
                print hello_world() - 21  # MyPy should fail. You can't subtract an `int` from `bytes`.
                """
            ),
            f"{PACKAGE}/BUILD": "python_sources(interpreter_constraints=['==2.7.*'])",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_mypy(
        rule_runner,
        [tgt],
        extra_args=[
            "--python-resolves={'mypy':'mypy.lock'}",
            "--mypy-install-from-resolve=mypy",
        ],
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/f.py:5: error: Unsupported operand types" in result[0].stdout
    # Confirm original issues not showing up.
    assert "Failed to execute PEX file" not in result[0].stderr
    assert (
        "Cannot find implementation or library stub for module named 'x690'" not in result[0].stdout
    )
    assert (
        "Cannot find implementation or library stub for module named 'libumi'"
        not in result[0].stdout
    )


@skip_unless_python38_present
def test_works_with_python38(rule_runner: PythonRuleRunner) -> None:
    """MyPy's typed-ast dependency does not understand Python 3.8, so we must instead run MyPy with
    Python 3.8 when relevant."""
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": dedent(
                """\
                x = 0
                if y := x:
                    print("x is truthy and now assigned to y")
                """
            ),
            f"{PACKAGE}/BUILD": "python_sources(interpreter_constraints=['>=3.8'])",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(rule_runner, tgt)


@skip_unless_python39_present
def test_works_with_python39(rule_runner: PythonRuleRunner) -> None:
    """MyPy's typed-ast dependency does not understand Python 3.9, so we must instead run MyPy with
    Python 3.9 when relevant."""
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": dedent(
                """\
                @lambda _: int
                def replaced(x: bool) -> str:
                    return "42" if x is True else "1/137"
                """
            ),
            f"{PACKAGE}/BUILD": "python_sources(interpreter_constraints=['>=3.9'])",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    assert_success(rule_runner, tgt)


@skip_unless_python27_and_python3_present
def test_uses_correct_python_version(rule_runner: PythonRuleRunner) -> None:
    """We set `--python-version` automatically for the user, and also batch based on interpreter
    constraints.

    This batching must consider transitive dependencies, so we use a more complex setup where the
    dependencies are what have specific constraints that influence the batching.
    """
    rule_runner.write_files(
        {
            "mypy.lock": read_sibling_resource(__name__, "older_mypy_for_testing.lock"),
            f"{PACKAGE}/py2/__init__.py": dedent(
                """\
                def add(x, y):
                    # type: (int, int) -> int
                    return x + y
                """
            ),
            f"{PACKAGE}/py2/BUILD": "python_sources(interpreter_constraints=['==2.7.*'])",
            f"{PACKAGE}/py3/__init__.py": dedent(
                """\
                def add(x: int, y: int) -> int:
                    return x + y
                """
            ),
            f"{PACKAGE}/py3/BUILD": "python_sources(interpreter_constraints=['>=3.6'])",
            f"{PACKAGE}/__init__.py": "",
            f"{PACKAGE}/uses_py2.py": "from project.py2 import add\nassert add(2, 2) == 4\n",
            f"{PACKAGE}/uses_py3.py": "from project.py3 import add\nassert add(2, 2) == 4\n",
            f"{PACKAGE}/BUILD": dedent(
                """python_sources(
                overrides={
                  'uses_py2.py': {'interpreter_constraints': ['==2.7.*']},
                  'uses_py3.py': {'interpreter_constraints': ['>=3.6']},
                }
              )
            """
            ),
        }
    )
    py2_tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="uses_py2.py"))
    py3_tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="uses_py3.py"))

    result = run_mypy(
        rule_runner,
        [py2_tgt, py3_tgt],
        extra_args=[
            "--python-resolves={'mypy':'mypy.lock'}",
            "--mypy-install-from-resolve=mypy",
        ],
    )
    assert len(result) == 2
    py2_result, py3_result = sorted(result, key=lambda res: res.partition_description or "")

    assert py2_result.exit_code == 0
    assert py2_result.partition_description == "['CPython==2.7.*']"
    assert "Success: no issues found" in py2_result.stdout

    assert py3_result.exit_code == 0
    assert py3_result.partition_description == "['CPython>=3.6']"
    assert "Success: no issues found" in py3_result.stdout


def test_run_only_on_specified_files(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/good.py": GOOD_FILE,
            f"{PACKAGE}/bad.py": BAD_FILE,
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_sources(name='good', sources=['good.py'], dependencies=[':bad'])
                python_sources(name='bad', sources=['bad.py'])
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, target_name="good", relative_file_path="good.py"))
    assert_success(rule_runner, tgt)


def test_type_stubs(rule_runner: PythonRuleRunner) -> None:
    """Test that first-party type stubs work for both first-party and third-party code."""
    rule_runner.write_files(
        {
            "BUILD": "python_requirement(name='colors', requirements=['ansicolors'])",
            "mypy_stubs/__init__.py": "",
            "mypy_stubs/colors.pyi": "def red(s: str) -> str: ...",
            "mypy_stubs/BUILD": "python_sources()",
            f"{PACKAGE}/util/__init__.py": "",
            f"{PACKAGE}/util/untyped.py": "def add(x, y):\n    return x + y",
            f"{PACKAGE}/util/untyped.pyi": "def add(x: int, y: int) -> int: ...",
            f"{PACKAGE}/util/BUILD": "python_sources()",
            f"{PACKAGE}/__init__.py": "",
            f"{PACKAGE}/app.py": dedent(
                """\
                from colors import red
                from project.util.untyped import add

                z = add(2, 2.0)
                print(red(z))
                """
            ),
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="app.py"))
    result = run_mypy(
        rule_runner, [tgt], extra_args=["--source-root-patterns=['mypy_stubs', 'src/py']"]
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/app.py:4: error: Argument 2 to" in result[0].stdout
    assert f"{PACKAGE}/app.py:5: error: Argument 1 to" in result[0].stdout


def test_mypy_shadows_requirements(rule_runner: PythonRuleRunner) -> None:
    """Test the behavior of a MyPy requirement shadowing a user's requirement.

    The way we load requirements is complex. We want to ensure that things still work properly in
    this edge case.
    """
    rule_runner.write_files(
        {
            "mypy.lock": read_sibling_resource(__name__, "mypy_shadowing_typed_ast.lock"),
            "BUILD": "python_requirement(name='ta', requirements=['typed-ast==1.4.1'])",
            f"{PACKAGE}/f.py": "import typed_ast",
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    extra_args = [
        "--python-resolves={'mypy':'mypy.lock'}",
        "--mypy-install-from-resolve=mypy",
    ]
    assert_success(rule_runner, tgt, extra_args=extra_args)


def test_source_plugin(rule_runner: PythonRuleRunner) -> None:
    # NB: We make this source plugin fairly complex by having it use transitive dependencies.
    # This is to ensure that we can correctly support plugins with dependencies.
    # The plugin changes the return type of functions ending in `__overridden_by_plugin` to have a
    # return type of `None`.
    plugin_file = dedent(
        """\
        from typing import Callable, Optional, Type

        from mypy.plugin import FunctionContext, Plugin
        from mypy.types import NoneType, Type as MyPyType

        from plugins.subdir.dep import is_overridable_function
        from project.subdir.util import noop

        noop()

        class ChangeReturnTypePlugin(Plugin):
            def get_function_hook(
                self, fullname: str
            ) -> Optional[Callable[[FunctionContext], MyPyType]]:
                return hook if is_overridable_function(fullname) else None

        def hook(ctx: FunctionContext) -> MyPyType:
            return NoneType()

        def plugin(_version: str) -> Type[Plugin]:
            return ChangeReturnTypePlugin
        """
    )
    rule_runner.write_files(
        {
            "mypy.lock": read_sibling_resource(__name__, "mypy_with_more_itertools.lock"),
            "BUILD": dedent(
                """\
                python_requirement(name='mypy', requirements=['mypy==1.1.1'])
                python_requirement(name="more-itertools", requirements=["more-itertools==8.4.0"])
                """
            ),
            "pants-plugins/plugins/subdir/__init__.py": "",
            "pants-plugins/plugins/subdir/dep.py": dedent(
                """\
                from more_itertools import flatten

                def is_overridable_function(name: str) -> bool:
                    assert list(flatten([[1, 2], [3, 4]])) == [1, 2, 3, 4]
                    return name.endswith("__overridden_by_plugin")
                """
            ),
            "pants-plugins/plugins/subdir/BUILD": "python_sources()",
            # The plugin can depend on code located anywhere in the project; its dependencies need
            # not be in the same directory.
            f"{PACKAGE}/subdir/__init__.py": "",
            f"{PACKAGE}/subdir/util.py": "def noop() -> None:\n    pass\n",
            f"{PACKAGE}/subdir/BUILD": "python_sources()",
            "pants-plugins/plugins/__init__.py": "",
            "pants-plugins/plugins/change_return_type.py": plugin_file,
            "pants-plugins/plugins/BUILD": "python_sources()",
            f"{PACKAGE}/__init__.py": "",
            f"{PACKAGE}/f.py": dedent(
                """\
                def add(x: int, y: int) -> int:
                    return x + y

                def add__overridden_by_plugin(x: int, y: int) -> int:
                    return x  + y

                result = add__overridden_by_plugin(1, 1)
                assert add(result, 2) == 4
                """
            ),
            f"{PACKAGE}/BUILD": "python_sources()",
            "mypy.ini": dedent(
                """\
                [mypy]
                plugins =
                    plugins.change_return_type
                """
            ),
        }
    )

    def run_mypy_with_plugin(tgt: Target) -> CheckResult:
        result = run_mypy(
            rule_runner,
            [tgt],
            extra_args=[
                "--python-resolves={'mypy':'mypy.lock'}",
                "--mypy-source-plugins=['pants-plugins/plugins']",
                "--mypy-install-from-resolve=mypy",
                "--source-root-patterns=['pants-plugins', 'src/py']",
            ],
        )
        assert len(result) == 1
        return result[0]

    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_mypy_with_plugin(tgt)
    assert result.exit_code == 1
    assert f"{PACKAGE}/f.py:8" in result.stdout
    # Ensure we don't accidentally check the source plugin itself.
    assert "(checked 1 source file)" in result.stdout

    # Ensure that running MyPy on the plugin itself still works.
    plugin_tgt = rule_runner.get_target(
        Address("pants-plugins/plugins", relative_file_path="change_return_type.py")
    )
    result = run_mypy_with_plugin(plugin_tgt)
    assert result.exit_code == 0
    assert "Success: no issues found in 1 source file" in result.stdout


def test_protobuf_mypy(rule_runner: PythonRuleRunner) -> None:
    rule_runner = PythonRuleRunner(
        rules=[*rule_runner.rules, *protobuf_rules(), *protobuf_subsystem_rules()],
        target_types=[*rule_runner.target_types, ProtobufSourceTarget],
    )
    rule_runner.write_files(
        {
            "BUILD": ("python_requirement(name='protobuf', requirements=['protobuf==3.13.0'])"),
            f"{PACKAGE}/__init__.py": "",
            f"{PACKAGE}/proto.proto": dedent(
                """\
                syntax = "proto3";
                package project;

                message Person {
                    string name = 1;
                    int32 id = 2;
                    string email = 3;
                }
                """
            ),
            f"{PACKAGE}/f.py": dedent(
                """\
                from project.proto_pb2 import Person

                x = Person(name=123, id="abc", email=None)
                """
            ),
            f"{PACKAGE}/BUILD": dedent(
                """\
                python_sources(dependencies=[':proto'])
                protobuf_source(name='proto', source='proto.proto')
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_mypy(
        rule_runner,
        [tgt],
        extra_args=["--python-protobuf-mypy-plugin"],
    )
    assert len(result) == 1
    assert 'Argument "name" to "Person" has incompatible type "int"' in result[0].stdout
    assert 'Argument "id" to "Person" has incompatible type "str"' in result[0].stdout
    assert result[0].exit_code == 1


@skip_unless_all_pythons_present("3.8", "3.9")
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
        **create_folder("resolveA_py38", "a", "3.8"),
        **create_folder("resolveA_py39", "a", "3.9"),
        **create_folder("resolveB_1", "b", "3.9"),
        **create_folder("resolveB_2", "b", "3.9"),
    }
    rule_runner.write_files(files)
    rule_runner.set_options(
        ["--python-resolves={'a': '', 'b': ''}", "--python-enable-resolves"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    resolve_a_py38_dep = rule_runner.get_target(Address("resolveA_py38", target_name="dep"))
    resolve_a_py38_root = rule_runner.get_target(Address("resolveA_py38", target_name="root"))
    resolve_a_py39_dep = rule_runner.get_target(Address("resolveA_py39", target_name="dep"))
    resolve_a_py39_root = rule_runner.get_target(Address("resolveA_py39", target_name="root"))
    resolve_b_dep1 = rule_runner.get_target(Address("resolveB_1", target_name="dep"))
    resolve_b_root1 = rule_runner.get_target(Address("resolveB_1", target_name="root"))
    resolve_b_dep2 = rule_runner.get_target(Address("resolveB_2", target_name="dep"))
    resolve_b_root2 = rule_runner.get_target(Address("resolveB_2", target_name="root"))
    request = MyPyRequest(
        MyPyFieldSet.create(t)
        for t in (
            resolve_a_py38_root,
            resolve_a_py39_root,
            resolve_b_root1,
            resolve_b_root2,
        )
    )

    partitions = rule_runner.request(MyPyPartitions, [request])
    assert len(partitions) == 3

    def assert_partition(
        partition: MyPyPartition,
        roots: list[Target],
        deps: list[Target],
        interpreter: str,
        resolve: str,
    ) -> None:
        root_addresses = {t.address for t in roots}
        assert {fs.address for fs in partition.field_sets} == root_addresses
        assert {t.address for t in partition.root_targets.closure()} == {
            *root_addresses,
            *(t.address for t in deps),
        }
        ics = [f"CPython=={interpreter}.*"]
        assert partition.interpreter_constraints == InterpreterConstraints(ics)
        assert partition.description() == f"{resolve}, {ics}"

    assert_partition(partitions[0], [resolve_a_py38_root], [resolve_a_py38_dep], "3.8", "a")
    assert_partition(partitions[1], [resolve_a_py39_root], [resolve_a_py39_dep], "3.9", "a")
    assert_partition(
        partitions[2],
        [resolve_b_root1, resolve_b_root2],
        [resolve_b_dep1, resolve_b_dep2],
        "3.9",
        "b",
    )


def test_determine_python_files() -> None:
    assert determine_python_files([]) == ()
    assert determine_python_files(["f.py"]) == ("f.py",)
    assert determine_python_files(["f.pyi"]) == ("f.pyi",)
    assert determine_python_files(["f.py", "f.pyi"]) == ("f.pyi",)
    assert determine_python_files(["f.pyi", "f.py"]) == ("f.pyi",)
    assert determine_python_files(["f.json"]) == ()


def test_colors_and_formatting(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": dedent(
                """\
                class incredibly_long_type_name_to_force_wrapping_if_mypy_wrapped_error_messages_12345678901234567890123456789012345678901234567890:
                    pass

                x = incredibly_long_type_name_to_force_wrapping_if_mypy_wrapped_error_messages_12345678901234567890123456789012345678901234567890()
                x.incredibly_long_attribute_name_to_force_wrapping_if_mypy_wrapped_error_messages_12345678901234567890123456789012345678901234567890
                """
            ),
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))

    result = run_mypy(rule_runner, [tgt], extra_args=["--colors=true", "--mypy-args=--pretty"])

    assert len(result) == 1
    assert result[0].exit_code == 1
    # all one line
    assert re.search(
        "error:.*incredibly_long_type_name.*incredibly_long_attribute_name", result[0].stdout
    )
    # at least one escape sequence that sets text color (red)
    assert "\033[31m" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST
