# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.python.dependency_inference.rules import (
    InferConftestDependencies,
    InferInitDependencies,
    InferPythonImportDependencies,
    PythonInferSubsystem,
    import_rules,
    infer_python_conftest_dependencies,
    infer_python_init_dependencies,
)
from pants.backend.python.target_types import (
    PythonLibrary,
    PythonRequirementLibrary,
    PythonSources,
    PythonTests,
)
from pants.backend.python.util_rules import ancestor_files
from pants.engine.addresses import Address
from pants.engine.rules import SubsystemRule
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_infer_python_imports() -> None:
    rule_runner = RuleRunner(
        rules=[*import_rules(), QueryRule(InferredDependencies, [InferPythonImportDependencies])],
        target_types=[PythonLibrary, PythonRequirementLibrary],
    )
    rule_runner.add_to_build_file(
        "3rdparty/python",
        dedent(
            """\
            python_requirement_library(
              name='Django',
              requirements=['Django==1.21'],
            )
            """
        ),
    )

    # If there's a `.py` and `.pyi` file for the same module, we should infer a dependency on both.
    rule_runner.create_file("src/python/str_import/subdir/f.py")
    rule_runner.create_file("src/python/str_import/subdir/f.pyi")
    rule_runner.add_to_build_file("src/python/str_import/subdir", "python_library()")

    rule_runner.create_file("src/python/util/dep.py")
    rule_runner.add_to_build_file("src/python/util", "python_library()")

    rule_runner.create_file(
        "src/python/app.py",
        dedent(
            """\
            import django
            import unrecognized.module

            from util.dep import Demo
            from util import dep
            """
        ),
    )
    rule_runner.create_file(
        "src/python/f2.py",
        dedent(
            """\
            import typing
            # Import from another file in the same target.
            from app import main

            # Dynamic string import.
            importlib.import_module('str_import.subdir.f')
            """
        ),
    )
    rule_runner.add_to_build_file("src/python", "python_library()")

    def run_dep_inference(
        address: Address, *, enable_string_imports: bool = False
    ) -> InferredDependencies:
        args = ["--backend-packages=pants.backend.python", "--source-root-patterns=src/python"]
        if enable_string_imports:
            args.append("--python-infer-string-imports")
        rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies, [InferPythonImportDependencies(target[PythonSources])]
        )

    build_address = Address("src/python")
    assert run_dep_inference(build_address) == InferredDependencies(
        [
            Address("3rdparty/python", target_name="Django"),
            Address("src/python", relative_file_path="app.py"),
            Address("src/python/util", relative_file_path="dep.py"),
        ],
        sibling_dependencies_inferrable=True,
    )

    file_address = Address("src/python", relative_file_path="f2.py")
    assert run_dep_inference(file_address) == InferredDependencies(
        [Address("src/python", relative_file_path="app.py")],
        sibling_dependencies_inferrable=True,
    )
    assert run_dep_inference(file_address, enable_string_imports=True) == InferredDependencies(
        [
            Address("src/python", relative_file_path="app.py"),
            Address("src/python/str_import/subdir", relative_file_path="f.py"),
            Address("src/python/str_import/subdir", relative_file_path="f.pyi"),
        ],
        sibling_dependencies_inferrable=True,
    )


def test_infer_python_inits() -> None:
    rule_runner = RuleRunner(
        rules=[
            *ancestor_files.rules(),
            infer_python_init_dependencies,
            SubsystemRule(PythonInferSubsystem),
            QueryRule(InferredDependencies, (InferInitDependencies,)),
        ],
        target_types=[PythonLibrary],
    )
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python",
            "--python-infer-inits",
            "--source-root-patterns=src/python",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    rule_runner.create_file("src/python/root/__init__.py")
    rule_runner.add_to_build_file("src/python/root", "python_library()")

    rule_runner.create_file("src/python/root/mid/__init__.py")
    rule_runner.add_to_build_file("src/python/root/mid", "python_library()")

    rule_runner.create_file("src/python/root/mid/leaf/__init__.py")
    rule_runner.add_to_build_file("src/python/root/mid/leaf", "python_library()")

    def run_dep_inference(address: Address) -> InferredDependencies:
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [InferInitDependencies(target[PythonSources])],
        )

    assert run_dep_inference(Address("src/python/root/mid/leaf")) == InferredDependencies(
        [
            Address("src/python/root", relative_file_path="__init__.py", target_name="root"),
            Address("src/python/root/mid", relative_file_path="__init__.py", target_name="mid"),
        ],
        sibling_dependencies_inferrable=False,
    )


def test_infer_python_conftests() -> None:
    rule_runner = RuleRunner(
        rules=[
            *ancestor_files.rules(),
            infer_python_conftest_dependencies,
            SubsystemRule(PythonInferSubsystem),
            QueryRule(InferredDependencies, (InferConftestDependencies,)),
        ],
        target_types=[PythonTests],
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python", "--source-root-patterns=src/python"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    rule_runner.create_file("src/python/root/conftest.py")
    rule_runner.add_to_build_file("src/python/root", "python_tests()")

    rule_runner.create_file("src/python/root/mid/conftest.py")
    rule_runner.add_to_build_file("src/python/root/mid", "python_tests()")

    rule_runner.create_file("src/python/root/mid/leaf/conftest.py")
    rule_runner.create_file("src/python/root/mid/leaf/this_is_a_test.py")
    rule_runner.add_to_build_file("src/python/root/mid/leaf", "python_tests()")

    def run_dep_inference(address: Address) -> InferredDependencies:
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [InferConftestDependencies(target[PythonSources])],
        )

    assert run_dep_inference(Address("src/python/root/mid/leaf")) == InferredDependencies(
        [
            Address("src/python/root", relative_file_path="conftest.py", target_name="root"),
            Address("src/python/root/mid", relative_file_path="conftest.py", target_name="mid"),
        ],
        sibling_dependencies_inferrable=False,
    )
