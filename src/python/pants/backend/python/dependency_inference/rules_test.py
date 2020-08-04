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
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.engine.addresses import Address
from pants.engine.rules import RootRule
from pants.engine.target import InferredDependencies, WrappedTarget
from pants.python.python_requirement import PythonRequirement
from pants.source.source_root import all_roots
from pants.testutil.engine.util import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PythonDependencyInferenceTest(TestBase):
    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(objects={"python_requirement": PythonRequirement})

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *strip_source_roots.rules(),
            *determine_source_files.rules(),
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
        options_bootstrapper = create_options_bootstrapper(
            args=["--backend-packages=pants.backend.python", "--source-root-patterns=src/python"]
        )
        self.add_to_build_file(
            "3rdparty/python",
            dedent(
                """\
                python_requirement_library(
                  name='Django',
                  requirements=[python_requirement('Django==1.21')],
                )
                """
            ),
        )

        self.create_file("src/python/no_owner/f.py")
        self.add_to_build_file("src/python/no_owner", "python_library()")

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
                """
            ),
        )
        self.add_to_build_file("src/python", "python_library()")

        def run_dep_inference(address: Address) -> InferredDependencies:
            target = self.request_single_product(WrappedTarget, address).target
            return self.request_single_product(
                InferredDependencies,
                Params(InferPythonDependencies(target[PythonSources]), options_bootstrapper),
            )

        # NB: We do not infer `src/python/app.py`, even though it's used by `src/python/f2.py`,
        # because it is part of the requested address.
        normal_address = Address("src/python")
        assert run_dep_inference(normal_address) == InferredDependencies(
            [
                Address("3rdparty/python", target_name="Django"),
                Address("src/python/util", relative_file_path="dep.py", target_name="util"),
            ]
        )

        generated_subtarget_address = Address(
            "src/python", relative_file_path="f2.py", target_name="python"
        )
        assert run_dep_inference(generated_subtarget_address) == InferredDependencies(
            [Address("src/python", relative_file_path="app.py", target_name="python")]
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
            target = self.request_single_product(WrappedTarget, address).target
            return self.request_single_product(
                InferredDependencies,
                Params(InferInitDependencies(target[PythonSources]), options_bootstrapper),
            )

        assert run_dep_inference(Address.parse("src/python/root/mid/leaf")) == InferredDependencies(
            [
                Address("src/python/root", relative_file_path="__init__.py", target_name="root"),
                Address("src/python/root/mid", relative_file_path="__init__.py", target_name="mid"),
            ]
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
            target = self.request_single_product(WrappedTarget, address).target
            return self.request_single_product(
                InferredDependencies,
                Params(InferConftestDependencies(target[PythonSources]), options_bootstrapper),
            )

        assert run_dep_inference(Address.parse("src/python/root/mid/leaf")) == InferredDependencies(
            [
                Address("src/python/root", relative_file_path="conftest.py", target_name="root"),
                Address("src/python/root/mid", relative_file_path="conftest.py", target_name="mid"),
            ]
        )
