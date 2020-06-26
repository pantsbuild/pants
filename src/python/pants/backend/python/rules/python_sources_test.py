# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Type

from pants.backend.python.rules.python_sources import (
    StrippedPythonSources,
    StrippedPythonSourcesRequest,
    UnstrippedPythonSources,
    UnstrippedPythonSourcesRequest,
)
from pants.backend.python.rules.python_sources import rules as python_sources_rules
from pants.backend.python.target_types import PythonSources
from pants.core.target_types import Files, Resources
from pants.engine.addresses import Address
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import Sources, Target
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PythonTarget(Target):
    alias = "python_target"
    core_fields = (PythonSources,)


class NonPythonTarget(Target):
    alias = "non_python_target"
    core_fields = (Sources,)


class StrippedPythonSourcesTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *python_sources_rules(),
            RootRule(StrippedPythonSourcesRequest),
            RootRule(UnstrippedPythonSourcesRequest),
        )

    def create_target(
        self, *, parent_directory: str, files: List[str], target_cls: Type[Target] = PythonTarget
    ) -> Target:
        self.create_files(parent_directory, files=files)
        address = Address(spec_path=parent_directory, target_name="target")
        return target_cls({Sources.alias: files}, address=address)

    def test_adds_missing_inits_and_strips_source_roots(self) -> None:
        target_with_init = self.create_target(
            parent_directory="src/python/project", files=["lib.py", "__init__.py"]
        )
        target_without_init = self.create_target(
            parent_directory="src/python/test_project", files=["f1.py", "f2.py"]
        )
        files_target = self.create_target(
            parent_directory="src/python/project/resources",
            files=["loose_file.txt"],
            target_cls=Files,
        )
        result = self.request_single_product(
            StrippedPythonSources,
            Params(
                StrippedPythonSourcesRequest(
                    [target_with_init, target_without_init, files_target], include_files=True
                ),
                create_options_bootstrapper(args=["--source-root-patterns=['src/python']"]),
            ),
        )
        assert sorted(result.snapshot.files) == sorted(
            [
                "project/lib.py",
                "project/__init__.py",
                "test_project/f1.py",
                "test_project/f2.py",
                "test_project/__init__.py",
                "src/python/project/resources/loose_file.txt",
            ]
        )

    def test_filters_out_irrelevant_targets(self) -> None:
        targets = [
            self.create_target(
                parent_directory="src/python", files=["p.py"], target_cls=PythonTarget
            ),
            self.create_target(parent_directory="src/python", files=["f.txt"], target_cls=Files),
            self.create_target(
                parent_directory="src/python", files=["r.txt"], target_cls=Resources
            ),
            self.create_target(
                parent_directory="src/python", files=["j.java"], target_cls=NonPythonTarget
            ),
        ]

        def assert_has_files(
            *, include_resources: bool, include_files: bool, expected: List[str]
        ) -> None:
            result = self.request_single_product(
                StrippedPythonSources,
                Params(
                    StrippedPythonSourcesRequest(
                        targets, include_resources=include_resources, include_files=include_files
                    ),
                    create_options_bootstrapper(),
                ),
            )
            assert result.snapshot.files == tuple(expected)

        assert_has_files(
            include_resources=True,
            include_files=True,
            expected=["p.py", "r.txt", "src/python/f.txt"],
        )
        assert_has_files(include_resources=True, include_files=False, expected=["p.py", "r.txt"])
        assert_has_files(
            include_resources=False, include_files=True, expected=["p.py", "src/python/f.txt"]
        )
        assert_has_files(include_resources=False, include_files=False, expected=["p.py"])


class UnstrippedPythonSourcesTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *python_sources_rules(),
            RootRule(StrippedPythonSourcesRequest),
            RootRule(UnstrippedPythonSourcesRequest),
        )

    def create_target(
        self, *, parent_directory: str, files: List[str], target_cls: Type[Target] = PythonTarget
    ) -> Target:
        self.create_files(parent_directory, files=files)
        address = Address(spec_path=parent_directory, target_name="target")
        return target_cls({Sources.alias: files}, address=address)

    def test_adds_missing_inits(self) -> None:
        target_with_init = self.create_target(
            parent_directory="src/python/project", files=["lib.py", "__init__.py"]
        )
        target_without_init = self.create_target(
            parent_directory="src/python/test_project", files=["f1.py", "f2.py"]
        )
        files_target = self.create_target(
            parent_directory="src/python/project/resources",
            files=["loose_file.txt"],
            target_cls=Files,
        )
        result = self.request_single_product(
            UnstrippedPythonSources,
            Params(
                UnstrippedPythonSourcesRequest(
                    [target_with_init, target_without_init, files_target], include_files=True
                ),
                create_options_bootstrapper(args=["--source-root-patterns=['src/python']"]),
            ),
        )
        assert sorted(result.snapshot.files) == sorted(
            [
                "src/python/project/lib.py",
                "src/python/project/__init__.py",
                "src/python/test_project/f1.py",
                "src/python/test_project/f2.py",
                "src/python/test_project/__init__.py",
                "src/python/project/resources/loose_file.txt",
            ]
        )

    def test_filters_out_irrelevant_targets(self) -> None:
        targets = [
            self.create_target(
                parent_directory="src/python", files=["p.py"], target_cls=PythonTarget
            ),
            self.create_target(parent_directory="src/python", files=["f.txt"], target_cls=Files),
            self.create_target(
                parent_directory="src/python", files=["r.txt"], target_cls=Resources
            ),
            self.create_target(
                parent_directory="src/python", files=["j.java"], target_cls=NonPythonTarget
            ),
        ]

        def assert_has_files(
            *, include_resources: bool, include_files: bool, expected: List[str]
        ) -> None:
            result = self.request_single_product(
                UnstrippedPythonSources,
                Params(
                    UnstrippedPythonSourcesRequest(
                        targets, include_resources=include_resources, include_files=include_files
                    ),
                    create_options_bootstrapper(),
                ),
            )
            assert result.snapshot.files == tuple(expected)

        assert_has_files(
            include_resources=True,
            include_files=True,
            expected=["src/python/f.txt", "src/python/p.py", "src/python/r.txt"],
        )
        assert_has_files(
            include_resources=True,
            include_files=False,
            expected=["src/python/p.py", "src/python/r.txt"],
        )
        assert_has_files(
            include_resources=False,
            include_files=True,
            expected=["src/python/f.txt", "src/python/p.py"],
        )
        assert_has_files(include_resources=False, include_files=False, expected=["src/python/p.py"])
