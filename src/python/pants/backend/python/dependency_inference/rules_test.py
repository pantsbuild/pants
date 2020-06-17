# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.python.dependency_inference.module_mapper import rules as module_mapper_rules
from pants.backend.python.dependency_inference.rules import (
    InferPythonDependencies,
    infer_python_dependencies,
)
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary, PythonSources
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.util_rules import strip_source_roots
from pants.engine.addresses import Address
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import InferredDependencies, WrappedTarget
from pants.python.python_requirement import PythonRequirement
from pants.source.source_root import all_roots
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
            infer_python_dependencies,
            *module_mapper_rules(),
            all_roots,
            RootRule(InferPythonDependencies),
        )

    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonRequirementLibrary]

    def test_infer_python_dependencies(self) -> None:
        options_bootstrapper = create_options_bootstrapper(
            args=["--source-root-patterns=src/python"]
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

        tgt = self.request_single_product(WrappedTarget, Address.parse("src/python")).target
        result = self.request_single_product(
            InferredDependencies,
            Params(InferPythonDependencies(tgt[PythonSources]), options_bootstrapper),
        )
        assert result == InferredDependencies(
            [Address.parse("3rdparty/python:Django"), Address.parse("src/python/util")]
        )
