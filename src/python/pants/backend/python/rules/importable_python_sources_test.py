# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import List, Optional, Type
from unittest.mock import Mock

from pants.backend.python.rules.importable_python_sources import ImportablePythonSources
from pants.backend.python.rules.importable_python_sources import (
    rules as importable_python_sources_rules,
)
from pants.build_graph.address import Address
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import Sources, Target, Targets
from pants.rules.core.targets import Files
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (Sources,)


class ImportablePythonSourcesTest(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), *importable_python_sources_rules(), RootRule(HydratedTargets))

    def create_target(
        self, *, parent_directory: str, files: List[str], target_cls: Type[Target] = MockTarget
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
            ImportablePythonSources,
            Params(
                Targets([target_with_init, target_without_init, files_target]),
                create_options_bootstrapper(),
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

    def make_hydrated_target(
        self, *, source_paths: List[str], type_alias: Optional[str] = None,
    ) -> HydratedTarget:
        adaptor = Mock()
        adaptor.type_alias = type_alias
        adaptor.sources = Mock()
        adaptor.sources.snapshot = self.make_snapshot_of_empty_files(source_paths)
        adaptor.address = Address(
            spec_path=PurePath(source_paths[0]).parent.as_posix(), target_name="target"
        )
        return HydratedTarget(adaptor)

    def test_legacy_adds_missing_inits_and_strips_source_roots(self) -> None:
        target_with_init = self.make_hydrated_target(
            source_paths=["src/python/project/lib.py", "src/python/project/__init__.py"],
        )
        target_without_init = self.make_hydrated_target(
            source_paths=["tests/python/test_project/f1.py", "tests/python/test_project/f2.py"],
        )
        files_target = self.make_hydrated_target(
            source_paths=["src/python/project/resources/loose_file.txt"], type_alias=Files.alias,
        )
        result = self.request_single_product(
            ImportablePythonSources,
            Params(
                HydratedTargets([target_with_init, target_without_init, files_target]),
                create_options_bootstrapper(),
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
