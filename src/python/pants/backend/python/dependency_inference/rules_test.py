# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.python.dependency_inference.rules import (
    InferConftestDependencies,
    InferInitDependencies,
    InferPythonDependencies,
)
from pants.backend.python.dependency_inference.rules import rules as dependency_inference_rules
from pants.backend.python.target_types import (
    PythonLibrary,
    PythonRequirementLibrary,
    PythonSources,
    PythonTests,
)
from pants.core.util_rules import source_files, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.rules import RootRule
from pants.engine.target import InferredDependencies, WrappedTarget
from pants.source.source_root import all_roots
from pants.testutil.engine_util import Params
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PythonDependencyInferenceTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *stripped_source_files.rules(),
            *source_files.rules(),
            *dependency_inference_rules(),
            all_roots,
            RootRule(InferPythonDependencies),
            RootRule(InferInitDependencies),
            RootRule(InferConftestDependencies),
        )

    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonRequirementLibrary, PythonTests]

    def test_infer_python_imports(self) -> None:
        self.add_to_build_file(
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

        self.create_file("src/python/str_import/subdir/f.py")
        self.add_to_build_file("src/python/str_import/subdir", "python_library()")

        self.create_file("src/python/util/dep.py")
        self.add_to_build_file("src/python/util", "python_library()")

        self.create_file(
            "src/python/app.py",
            dedent(
                """\
                import django

                from util.dep import Demo
                from util import dep
                """
            ),
        )
        self.create_file(
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
        self.add_to_build_file("src/python", "python_library()")

        def run_dep_inference(
            address: Address, *, enable_string_imports: bool = False
        ) -> InferredDependencies:
            args = ["--backend-packages=pants.backend.python", "--source-root-patterns=src/python"]
            if enable_string_imports:
                args.append("--python-infer-string-imports")
            options_bootstrapper = create_options_bootstrapper(args=args)
            target = self.request_product(
                WrappedTarget, Params(address, options_bootstrapper)
            ).target
            return self.request_product(
                InferredDependencies,
                Params(InferPythonDependencies(target[PythonSources]), options_bootstrapper),
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

    def test_infer_python_inits(self) -> None:
        options_bootstrapper = create_options_bootstrapper(
            args=["--backend-packages=pants.backend.python", "--source-root-patterns=src/python",]
        )

        self.create_file("src/python/root/__init__.py")
        self.add_to_build_file("src/python/root", "python_library()")

        self.create_file("src/python/root/mid/__init__.py")
        self.add_to_build_file("src/python/root/mid", "python_library()")

        self.create_file("src/python/root/mid/leaf/__init__.py")
        self.add_to_build_file("src/python/root/mid/leaf", "python_library()")

        def run_dep_inference(address: Address) -> InferredDependencies:
            target = self.request_product(
                WrappedTarget, Params(address, options_bootstrapper)
            ).target
            return self.request_product(
                InferredDependencies,
                Params(InferInitDependencies(target[PythonSources]), options_bootstrapper),
            )

        assert run_dep_inference(Address.parse("src/python/root/mid/leaf")) == InferredDependencies(
            [
                Address("src/python/root", relative_file_path="__init__.py", target_name="root"),
                Address("src/python/root/mid", relative_file_path="__init__.py", target_name="mid"),
            ],
            sibling_dependencies_inferrable=False,
        )

    def test_infer_python_conftests(self) -> None:
        options_bootstrapper = create_options_bootstrapper(
            args=["--backend-packages=pants.backend.python", "--source-root-patterns=src/python",]
        )

        self.create_file("src/python/root/conftest.py")
        self.add_to_build_file("src/python/root", "python_library(sources=['conftest.py'])")

        self.create_file("src/python/root/mid/conftest.py")
        self.add_to_build_file("src/python/root/mid", "python_library(sources=['conftest.py'])")

        self.create_file("src/python/root/mid/leaf/conftest.py")
        self.create_file("src/python/root/mid/leaf/this_is_a_test.py")
        self.add_to_build_file("src/python/root/mid/leaf", "python_tests()")

        def run_dep_inference(address: Address) -> InferredDependencies:
            target = self.request_product(
                WrappedTarget, Params(address, options_bootstrapper)
            ).target
            return self.request_product(
                InferredDependencies,
                Params(InferConftestDependencies(target[PythonSources]), options_bootstrapper),
            )

        assert run_dep_inference(Address.parse("src/python/root/mid/leaf")) == InferredDependencies(
            [
                Address("src/python/root", relative_file_path="conftest.py", target_name="root"),
                Address("src/python/root/mid", relative_file_path="conftest.py", target_name="mid"),
            ],
            sibling_dependencies_inferrable=False,
        )
