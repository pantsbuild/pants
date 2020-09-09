# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from textwrap import dedent
from typing import List, Optional, Sequence

import pytest

from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.backend.python.typecheck.mypy.rules import MyPyFieldSet, MyPyRequest
from pants.backend.python.typecheck.mypy.rules import rules as mypy_rules
from pants.core.goals.typecheck import TypecheckResult, TypecheckResults
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.python_interpreter_selection import skip_unless_python38_present
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *mypy_rules(),
            *dependency_inference_rules.rules(),  # Used for import inference.
            QueryRule(TypecheckResults, (MyPyRequest, OptionsBootstrapper)),
        ],
        target_types=[PythonLibrary, PythonRequirementLibrary],
    )


PACKAGE = "src/python/project"
GOOD_SOURCE = FileContent(
    f"{PACKAGE}/good.py",
    dedent(
        """\
        def add(x: int, y: int) -> int:
            return x + y

        result = add(3, 3)
        """
    ).encode(),
)
BAD_SOURCE = FileContent(
    f"{PACKAGE}/bad.py",
    dedent(
        """\
        def add(x: int, y: int) -> int:
            return x + y

        result = add(2.0, 3.0)
        """
    ).encode(),
)
NEEDS_CONFIG_SOURCE = FileContent(
    f"{PACKAGE}/needs_config.py",
    dedent(
        """\
        from typing import Any, cast

        # This will fail if `--disallow-any-expr` is configured.
        x = cast(Any, "hello")
        """
    ).encode(),
)

GLOBAL_ARGS = (
    "--backend-packages=pants.backend.python",
    "--backend-packages=pants.backend.python.typecheck.mypy",
    "--source-root-patterns=['src/python', 'tests/python']",
)


def make_target(
    rule_runner: RuleRunner,
    source_files: List[FileContent],
    *,
    package: Optional[str] = None,
    name: str = "target",
    interpreter_constraints: Optional[str] = None,
) -> Target:
    if not package:
        package = PACKAGE
    for source_file in source_files:
        rule_runner.create_file(source_file.path, source_file.content.decode())
    source_globs = [PurePath(source_file.path).name for source_file in source_files]
    rule_runner.add_to_build_file(
        f"{package}",
        dedent(
            f"""\
            python_library(
                name={repr(name)},
                sources={source_globs},
                compatibility={repr(interpreter_constraints)},
            )
            """
        ),
    )
    return rule_runner.get_target(
        Address(package, target_name=name), create_options_bootstrapper(args=GLOBAL_ARGS)
    )


def run_mypy(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    skip: bool = False,
    additional_args: Optional[List[str]] = None,
) -> Sequence[TypecheckResult]:
    args = list(GLOBAL_ARGS)
    if config:
        rule_runner.create_file(relpath="mypy.ini", contents=config)
        args.append("--mypy-config=mypy.ini")
    if passthrough_args:
        args.append(f"--mypy-args='{passthrough_args}'")
    if skip:
        args.append("--mypy-skip")
    if additional_args:
        args.extend(additional_args)
    result = rule_runner.request_product(
        TypecheckResults,
        [
            MyPyRequest(MyPyFieldSet.create(tgt) for tgt in targets),
            create_options_bootstrapper(args=args),
        ],
    )
    return result.results


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    result = run_mypy(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Success: no issues found" in result[0].stdout.strip()


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_mypy(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/bad.py:4" in result[0].stdout


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    result = run_mypy(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/good.py" not in result[0].stdout
    assert f"{PACKAGE}/bad.py:4" in result[0].stdout
    assert "checked 2 source files" in result[0].stdout


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE], name="t1"),
        make_target(rule_runner, [BAD_SOURCE], name="t2"),
    ]
    result = run_mypy(rule_runner, targets)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/good.py" not in result[0].stdout
    assert f"{PACKAGE}/bad.py:4" in result[0].stdout
    assert "checked 2 source files" in result[0].stdout


def test_respects_config_file(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [NEEDS_CONFIG_SOURCE])
    result = run_mypy(rule_runner, [target], config="[mypy]\ndisallow_any_expr = True\n")
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/needs_config.py:4" in result[0].stdout


def test_respects_passthrough_args(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [NEEDS_CONFIG_SOURCE])
    result = run_mypy(rule_runner, [target], passthrough_args="--disallow-any-expr")
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/needs_config.py:4" in result[0].stdout


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    result = run_mypy(rule_runner, [target], skip=True)
    assert not result


def test_thirdparty_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            python_requirement_library(
                name="more-itertools",
                requirements=["more-itertools==8.4.0"],
            )
            """
        ),
    )
    source_file = FileContent(
        f"{PACKAGE}/itertools.py",
        dedent(
            """\
            from more_itertools import flatten

            assert flatten(42) == [4, 2]
            """
        ).encode(),
    )
    target = make_target(rule_runner, [source_file])
    result = run_mypy(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/itertools.py:3" in result[0].stdout


def test_thirdparty_plugin(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            python_requirement_library(
                name='django',
                requirements=['Django==2.2.5'],
            )
            """
        ),
    )
    settings_file = FileContent(
        f"{PACKAGE}/settings.py",
        dedent(
            """\
            from django.urls import URLPattern

            DEBUG = True
            DEFAULT_FROM_EMAIL = "webmaster@example.com"
            SECRET_KEY = "not so secret"
            MY_SETTING = URLPattern(pattern="foo", callback=lambda: None)
            """
        ).encode(),
    )
    app_file = FileContent(
        f"{PACKAGE}/app.py",
        dedent(
            """\
            from django.utils import text

            assert "forty-two" == text.slugify("forty two")
            assert "42" == text.slugify(42)
            """
        ).encode(),
    )
    target = make_target(rule_runner, [settings_file, app_file])
    config_content = dedent(
        """\
        [mypy]
        plugins =
            mypy_django_plugin.main

        [mypy.plugins.django-stubs]
        django_settings_module = project.settings
        """
    )
    result = run_mypy(
        rule_runner,
        [target],
        config=config_content,
        additional_args=[
            "--mypy-extra-requirements=django-stubs==1.5.0",
            "--mypy-version=mypy==0.770",
        ],
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "src/python/project/app.py:4" in result[0].stdout


def test_transitive_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.create_file(f"{PACKAGE}/util/__init__.py")
    rule_runner.create_file(
        f"{PACKAGE}/util/lib.py",
        dedent(
            """\
            def capitalize(v: str) -> str:
                return v.capitalize()
            """
        ),
    )
    rule_runner.add_to_build_file(f"{PACKAGE}/util", "python_library()")

    rule_runner.create_file(f"{PACKAGE}/math/__init__.py")
    rule_runner.create_file(
        f"{PACKAGE}/math/add.py",
        dedent(
            """\
            from project.util.lib import capitalize

            def add(x: int, y: int) -> str:
                sum = x + y
                return capitalize(sum)  # This is the wrong type.
            """
        ),
    )
    rule_runner.add_to_build_file(
        f"{PACKAGE}/math",
        "python_library()",
    )

    sources_content = [
        FileContent(
            f"{PACKAGE}/app.py",
            dedent(
                """\
                from project.math.add import add

                print(add(2, 4))
                """
            ).encode(),
        ),
        FileContent(f"{PACKAGE}/__init__.py", b""),
    ]
    target = make_target(rule_runner, sources_content)
    result = run_mypy(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/math/add.py:5" in result[0].stdout


@skip_unless_python38_present
def test_works_with_python38(rule_runner: RuleRunner) -> None:
    """MyPy's typed-ast dependency does not understand Python 3.8, so we must instead run MyPy with
    Python 3.8 when relevant."""
    rule_runner.create_file(f"{PACKAGE}/__init__.py")
    py38_sources = FileContent(
        f"{PACKAGE}/py38.py",
        dedent(
            """\
            x = 0
            if y := x:
                print("x is truthy and now assigned to y")
            """
        ).encode(),
    )
    target = make_target(rule_runner, [py38_sources], interpreter_constraints=">=3.8")
    result = run_mypy(rule_runner, [target])
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Success: no issues found" in result[0].stdout.strip()
