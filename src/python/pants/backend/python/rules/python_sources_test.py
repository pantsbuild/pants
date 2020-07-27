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
