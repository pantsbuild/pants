# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.python.dependency_inference import module_mapper
from pants.backend.python.dependency_inference.rules import (
    InferConftestDependencies,
    InferInitDependencies,
    InferPythonDependencies,
    PythonInference,
    infer_python_conftest_dependencies,
    infer_python_dependencies,
    infer_python_init_dependencies,
)
from pants.backend.python.rules import ancestor_files
from pants.backend.python.target_types import (
    PythonLibrary,
    PythonRequirementLibrary,
    PythonSources,
    PythonTests,
)
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule, SubsystemRule
from pants.engine.target import InferredDependencies, WrappedTarget
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import RuleRunner


def test_infer_python_imports() -> None:
    rule_runner = RuleRunner(
        rules=[
            *stripped_source_files.rules(),
            *module_mapper.rules(),
            infer_python_dependencies,
            SubsystemRule(PythonInference),
            QueryRule(InferredDependencies, (InferPythonDependencies, OptionsBootstrapper)),
        ],
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

    rule_runner.create_file("src/python/str_import/subdir/f.py")
    rule_runner.add_to_build_file("src/python/str_import/subdir", "python_library()")

    rule_runner.create_file("src/python/util/dep.py")
    rule_runner.add_to_build_file("src/python/util", "python_library()")

    rule_runner.create_file(
        "src/python/app.py",
        dedent(
            """\
            import django

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
        options_bootstrapper = create_options_bootstrapper(args=args)
        target = rule_runner.request_product(WrappedTarget, [address, options_bootstrapper]).target
        return rule_runner.request_product(
            InferredDependencies,
            [InferPythonDependencies(target[PythonSources]), options_bootstrapper],
        )

    normal_address = Address("src/python")
    assert run_dep_inference(normal_address) == InferredDependencies(
        [
            Address("3rdparty/python", target_name="Django"),
            Address("src/python", relative_file_path="app.py"),
            Address("src/python/util", relative_file_path="dep.py", target_name="util"),
        ],
        sibling_dependencies_inferrable=True,
    )

    generated_subtarget_address = Address(
        "src/python", relative_file_path="f2.py", target_name="python"
    )
    assert run_dep_inference(generated_subtarget_address) == InferredDependencies(
        [Address("src/python", relative_file_path="app.py", target_name="python")],
        sibling_dependencies_inferrable=True,
    )
    assert run_dep_inference(
        generated_subtarget_address, enable_string_imports=True
    ) == InferredDependencies(
        [
            Address("src/python", relative_file_path="app.py", target_name="python"),
            Address("src/python/str_import/subdir", relative_file_path="f.py"),
        ],
        sibling_dependencies_inferrable=True,
    )


def test_infer_python_inits() -> None:
    rule_runner = RuleRunner(
        rules=[
            *ancestor_files.rules(),
            infer_python_init_dependencies,
            SubsystemRule(PythonInference),
            QueryRule(InferredDependencies, (InferInitDependencies, OptionsBootstrapper)),
        ],
        target_types=[PythonLibrary],
    )
    options_bootstrapper = create_options_bootstrapper(
        args=[
            "--backend-packages=pants.backend.python",
            "--source-root-patterns=src/python",
        ]
    )

    rule_runner.create_file("src/python/root/__init__.py")
    rule_runner.add_to_build_file("src/python/root", "python_library()")

    rule_runner.create_file("src/python/root/mid/__init__.py")
    rule_runner.add_to_build_file("src/python/root/mid", "python_library()")

    rule_runner.create_file("src/python/root/mid/leaf/__init__.py")
    rule_runner.add_to_build_file("src/python/root/mid/leaf", "python_library()")

    def run_dep_inference(address: Address) -> InferredDependencies:
        target = rule_runner.request_product(WrappedTarget, [address, options_bootstrapper]).target
        return rule_runner.request_product(
            InferredDependencies,
            [InferInitDependencies(target[PythonSources]), options_bootstrapper],
        )

    assert run_dep_inference(Address.parse("src/python/root/mid/leaf")) == InferredDependencies(
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
            SubsystemRule(PythonInference),
            QueryRule(InferredDependencies, (InferConftestDependencies, OptionsBootstrapper)),
        ],
        target_types=[PythonTests],
    )
    options_bootstrapper = create_options_bootstrapper(
        args=[
            "--backend-packages=pants.backend.python",
            "--source-root-patterns=src/python",
        ]
    )

    rule_runner.create_file("src/python/root/conftest.py")
    rule_runner.add_to_build_file("src/python/root", "python_tests()")

    rule_runner.create_file("src/python/root/mid/conftest.py")
    rule_runner.add_to_build_file("src/python/root/mid", "python_tests()")

    rule_runner.create_file("src/python/root/mid/leaf/conftest.py")
    rule_runner.create_file("src/python/root/mid/leaf/this_is_a_test.py")
    rule_runner.add_to_build_file("src/python/root/mid/leaf", "python_tests()")

    def run_dep_inference(address: Address) -> InferredDependencies:
        target = rule_runner.request_product(WrappedTarget, [address, options_bootstrapper]).target
        return rule_runner.request_product(
            InferredDependencies,
            [InferConftestDependencies(target[PythonSources]), options_bootstrapper],
        )

    assert run_dep_inference(Address.parse("src/python/root/mid/leaf")) == InferredDependencies(
        [
            Address("src/python/root", relative_file_path="conftest.py", target_name="root"),
            Address("src/python/root/mid", relative_file_path="conftest.py", target_name="mid"),
        ],
        sibling_dependencies_inferrable=False,
    )
