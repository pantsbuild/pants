# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path, PurePath
from textwrap import dedent
from typing import List, Optional, Sequence

import pytest

from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.backend.python.typecheck.mypy.plugin_target_type import MyPySourcePlugin
from pants.backend.python.typecheck.mypy.rules import MyPyFieldSet, MyPyRequest
from pants.backend.python.typecheck.mypy.rules import rules as mypy_rules
from pants.core.goals.typecheck import TypecheckResult, TypecheckResults
from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.python_interpreter_selection import (
    skip_unless_python27_present,
    skip_unless_python38_present,
)
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *mypy_rules(),
            *dependency_inference_rules.rules(),  # Used for import inference.
            QueryRule(TypecheckResults, (MyPyRequest, PantsEnvironment)),
        ],
        target_types=[PythonLibrary, PythonRequirementLibrary, MyPySourcePlugin],
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
    "--source-root-patterns=['/', 'src/python', 'tests/python']",
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
    result = rule_runner.request(
        TypecheckResults,
        [
            MyPyRequest(MyPyFieldSet.create(tgt) for tgt in targets),
            create_options_bootstrapper(args=args),
            PantsEnvironment(),
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
    # We hijack `--mypy-source-plugins` for our settings.py file to ensure that it is always used,
    # even if the files we're checking don't need it. Typically, this option expects
    # `mypy_source_plugin` targets, but that's not actually validated. We only want this specific
    # file to be permanently included, not the whole original target, so we will use a file address.
    rule_runner.create_file(
        f"{PACKAGE}/settings.py",
        dedent(
            """\
            from django.urls import URLPattern

            DEBUG = True
            DEFAULT_FROM_EMAIL = "webmaster@example.com"
            SECRET_KEY = "not so secret"
            MY_SETTING = URLPattern(pattern="foo", callback=lambda: None)
            """
        ),
    )
    rule_runner.create_file(
        f"{PACKAGE}/app.py",
        dedent(
            """\
            from django.utils import text

            assert "forty-two" == text.slugify("forty two")
            assert "42" == text.slugify(42)
            """
        ),
    )
    rule_runner.add_to_build_file(PACKAGE, "python_library()")
    app_tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="app.py"))

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
        [app_tgt],
        config=config_content,
        additional_args=[
            "--mypy-extra-requirements=django-stubs==1.5.0",
            "--mypy-version=mypy==0.770",
            f"--mypy-source-plugins={PACKAGE}/settings.py",
        ],
    )
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "src/python/project/app.py:4" in result[0].stdout

    # We also test that loading a plugin by using a 3rd-party requirement still works.
    Path(rule_runner.build_root, PACKAGE, "BUILD").unlink()
    rule_runner.add_to_build_file(
        PACKAGE,
        dedent(
            """\
            python_requirement_library(
                name="django-stubs",
                requirements=["django-stubs==1.5.0"],
            )

            # The `./settings.py` dependency ensures that it will always be loaded.
            python_library(dependencies=[":django-stubs", "./settings.py"])
            """
        ),
    )
    app_tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="app.py"))
    result = run_mypy(
        rule_runner,
        [app_tgt],
        config=config_content,
        additional_args=["--mypy-version=mypy==0.770"],
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


@skip_unless_python27_present
def test_works_with_python27(rule_runner: RuleRunner) -> None:
    """A regression test that we can properly handle Python 2-only third-party dependencies.

    There was a bug that this would cause the runner PEX to fail to execute because it did not have
    Python 3 distributions of the requirements.
    """
    rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            # Both requirements are a) typed and b) compatible with Py2 and Py3. However, `x690`
            # has a distinct wheel for Py2 vs. Py3, whereas libumi has a universal wheel. We expect 
            # both to be usable, even though libumi is not compatible with Py3. 

            python_requirement_library(
                name="libumi",
                requirements=["libumi==0.0.2"],
            )

            python_requirement_library(
                name="x690",
                requirements=["x690==0.2.0"],
            )
            """
        ),
    )
    source_file = FileContent(
        f"{PACKAGE}/py2.py",
        dedent(
            """\
            from libumi import hello_world
            from x690 import types

            print "Blast from the past!"
            print hello_world() - 21  # MyPy should fail. You can't subtract an `int` from `bytes`.
            """
        ).encode(),
    )
    target = make_target(rule_runner, [source_file], interpreter_constraints="==2.7.*")
    result = run_mypy(rule_runner, [target], passthrough_args="--py2")
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "Failed to execute PEX file" not in result[0].stderr
    assert (
        "Cannot find implementation or library stub for module named 'x690'" not in result[0].stdout
    )
    assert (
        "Cannot find implementation or library stub for module named 'libumi'"
        not in result[0].stdout
    )
    assert f"{PACKAGE}/py2.py:5: error: Unsupported operand types" in result[0].stdout


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


def test_mypy_shadows_requirements(rule_runner: RuleRunner) -> None:
    """Test the behavior of a MyPy requirement shadowing a user's requirement.

    The way we load requirements is complex. We want to ensure that things still work properly in
    this edge case.
    """
    rule_runner.create_file("app.py", "import typed_ast\n")
    rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            python_requirement_library(
                name='typed-ast',
                requirements=['typed-ast==1.4.1'],
            )

            python_library(name="lib")
            """
        ),
    )
    tgt = rule_runner.get_target(Address("", target_name="lib"))
    result = run_mypy(rule_runner, [tgt], additional_args=["--mypy-version=mypy==0.782"])
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "Success: no issues found" in result[0].stdout


def test_source_plugin(rule_runner: RuleRunner) -> None:
    # NB: We make this source plugin fairly complex by having it use transitive dependencies.
    # This is to ensure that we can correctly support plugins with dependencies.
    # The plugin changes the return type of functions ending in `__overridden_by_plugin` to have a
    # return type of `None`.
    rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            python_requirement_library(
                name='mypy',
                requirements=['mypy==0.782'],
            )

            python_requirement_library(
                name="more-itertools",
                requirements=["more-itertools==8.4.0"],
            )
            """
        ),
    )
    rule_runner.create_file("pants-plugins/plugins/subdir/__init__.py")
    rule_runner.create_file(
        "pants-plugins/plugins/subdir/dep.py",
        dedent(
            """\
            from more_itertools import flatten

            def is_overridable_function(name: str) -> bool:
                assert list(flatten([[1, 2], [3, 4]])) == [1, 2, 3, 4]
                return name.endswith("__overridden_by_plugin")
            """
        ),
    )
    rule_runner.add_to_build_file("pants-plugins/plugins/subdir", "python_library()")

    # The plugin can depend on code located anywhere in the project; its dependencies need not be in
    # the same directory.
    rule_runner.create_file(f"{PACKAGE}/__init__.py")
    rule_runner.create_file(f"{PACKAGE}/subdir/__init__.py")
    rule_runner.create_file(f"{PACKAGE}/subdir/util.py", "def noop() -> None:\n    pass\n")
    rule_runner.add_to_build_file(f"{PACKAGE}/subdir", "python_library()")

    rule_runner.create_file("pants-plugins/plugins/__init__.py")
    rule_runner.create_file(
        "pants-plugins/plugins/change_return_type.py",
        dedent(
            """\
            from typing import Callable, Optional, Type

            from mypy.plugin import FunctionContext, Plugin
            from mypy.types import NoneType, Type as MyPyType

            from plugins.subdir.dep import is_overridable_function
            from project.subdir.util import noop

            noop()

            class AutoAddFieldPlugin(Plugin):
                def get_function_hook(
                    self, fullname: str
                ) -> Optional[Callable[[FunctionContext], MyPyType]]:
                    return hook if is_overridable_function(fullname) else None


            def hook(ctx: FunctionContext) -> MyPyType:
                return NoneType()


            def plugin(_version: str) -> Type[Plugin]:
                return AutoAddFieldPlugin
            """
        ),
    )
    rule_runner.add_to_build_file(
        "pants-plugins/plugins",
        dedent(
            """\
            mypy_source_plugin(
                name='change_return_type',
                sources=['change_return_type.py'],
            )
            """
        ),
    )

    config_content = dedent(
        """\
        [mypy]
        plugins =
            plugins.change_return_type
        """
    )

    test_file_content = dedent(
        """\
        def add(x: int, y: int) -> int:
            return x + y


        def add__overridden_by_plugin(x: int, y: int) -> int:
            return x  + y


        result = add__overridden_by_plugin(1, 1)
        assert add(result, 2) == 4
        """
    ).encode()

    def run_mypy_with_plugin(tgt: Target) -> TypecheckResult:
        result = run_mypy(
            rule_runner,
            [tgt],
            additional_args=[
                "--mypy-source-plugins=['pants-plugins/plugins:change_return_type']",
                "--source-root-patterns=['pants-plugins', 'src/python']",
            ],
            config=config_content,
        )
        assert len(result) == 1
        return result[0]

    target = make_target(
        rule_runner, [FileContent(f"{PACKAGE}/test_source_plugin.py", test_file_content)]
    )
    result = run_mypy_with_plugin(target)
    assert result.exit_code == 1
    assert f"{PACKAGE}/test_source_plugin.py:10" in result.stdout
    # We want to ensure we don't accidentally check the source plugin itself.
    assert "(checked 2 source files)" in result.stdout

    # We also want to ensure that running MyPy on the plugin itself still works.
    plugin_tgt = rule_runner.get_target(
        Address("pants-plugins/plugins", target_name="change_return_type")
    )
    result = run_mypy_with_plugin(plugin_tgt)
    assert result.exit_code == 0
    assert "Success: no issues found in 7 source files" in result.stdout
