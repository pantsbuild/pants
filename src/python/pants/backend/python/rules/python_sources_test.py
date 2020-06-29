# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Type, Union, cast

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


class PythonSourcesTest(TestBase):
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
        # Create an __init__.py not included in any targets. This should be automatically added.
        self.create_file("src/python/test_project/__init__.py")
        target_with_undeclared_init = self.create_target(
            parent_directory="src/python/test_project", files=["f1.py", "f2.py"]
        )
        files_target = self.create_target(
            parent_directory="src/python/project/resources",
            files=["loose_file.txt"],
            target_cls=Files,
        )
        targets = [target_with_init, target_with_undeclared_init, files_target]

        stripped_result = self.request_single_product(
            StrippedPythonSources,
            Params(
                StrippedPythonSourcesRequest(targets, include_files=True),
                create_options_bootstrapper(),
            ),
        )
        assert sorted(stripped_result.snapshot.files) == sorted(
            [
                "project/lib.py",
                "project/__init__.py",
                "test_project/f1.py",
                "test_project/f2.py",
                "test_project/__init__.py",
                "src/python/project/resources/loose_file.txt",
            ]
        )

        unstripped_result = self.request_single_product(
            UnstrippedPythonSources,
            Params(
                UnstrippedPythonSourcesRequest(targets, include_files=True),
                create_options_bootstrapper(),
            ),
        )
        assert sorted(unstripped_result.snapshot.files) == sorted(
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
            *, include_resources: bool, include_files: bool, is_stripped: bool, expected: List[str],
        ) -> None:
            product = StrippedPythonSources if is_stripped else UnstrippedPythonSources
            subject = (
                StrippedPythonSourcesRequest if is_stripped else UnstrippedPythonSourcesRequest
            )
            result = cast(
                Union[StrippedPythonSources, UnstrippedPythonSources],
                self.request_single_product(
                    product,
                    Params(
                        subject(
                            targets,
                            include_resources=include_resources,
                            include_files=include_files,
                        ),
                        create_options_bootstrapper(),
                    ),
                ),
            )
            assert result.snapshot.files == tuple(expected)

        assert_has_files(
            include_resources=True,
            include_files=True,
            is_stripped=True,
            expected=["p.py", "r.txt", "src/python/f.txt"],
        )
        assert_has_files(
            include_resources=True,
            include_files=True,
            is_stripped=False,
            expected=["src/python/f.txt", "src/python/p.py", "src/python/r.txt"],
        )

        assert_has_files(
            include_resources=True,
            include_files=False,
            is_stripped=True,
            expected=["p.py", "r.txt"],
        )
        assert_has_files(
            include_resources=True,
            include_files=False,
            is_stripped=False,
            expected=["src/python/p.py", "src/python/r.txt"],
        )

        assert_has_files(
            include_resources=False,
            include_files=True,
            is_stripped=True,
            expected=["p.py", "src/python/f.txt"],
        )
        assert_has_files(
            include_resources=False,
            include_files=True,
            is_stripped=False,
            expected=["src/python/f.txt", "src/python/p.py"],
        )

        assert_has_files(
            include_resources=False, include_files=False, is_stripped=True, expected=["p.py"]
        )
        assert_has_files(
            include_resources=False,
            include_files=False,
            is_stripped=False,
            expected=["src/python/p.py"],
        )
