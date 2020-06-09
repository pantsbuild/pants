# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.project_info.list_roots import all_roots
from pants.backend.python.dependency_inference.module_mapper import map_python_module_to_targets
from pants.backend.python.dependency_inference.rules import (
    InferPythonDependencies,
    infer_python_dependencies,
)
from pants.backend.python.target_types import PythonLibrary, PythonSources
from pants.core.util_rules import strip_source_roots
from pants.engine.addresses import Address
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import InferredDependencies, WrappedTarget
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PythonDependencyInferenceTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *strip_source_roots.rules(),
            infer_python_dependencies,
            map_python_module_to_targets,
            all_roots,
            RootRule(InferPythonDependencies),
        )

    @classmethod
    def target_types(cls):
        return [PythonLibrary]

    def test_map_module_to_targets(self) -> None:
        options_bootstrapper = create_options_bootstrapper(
            args=["--source-root-patterns=src/python"]
        )
        self.create_file("src/python/no_owner/f.py")
        self.add_to_build_file("src/python/no_owner", "python_library()")

        self.create_file("src/python/util/dep.py")
        self.add_to_build_file("src/python/util", "python_library()")

        self.create_file(
            "src/python/app.py",
            dedent(
                """\
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
        assert result == InferredDependencies([Address.parse("src/python/util")])
