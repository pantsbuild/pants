# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import List, Optional
from unittest.mock import Mock

from pants.backend.python.rules.prepare_chrooted_python_sources import ChrootedPythonSources
from pants.backend.python.rules.prepare_chrooted_python_sources import (
    rules as prepare_chrooted_python_sources_rules,
)
from pants.build_graph.address import Address
from pants.build_graph.files import Files
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core import strip_source_roots
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PrepareChrootedPythonSourcesTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *strip_source_roots.rules(),
            *prepare_chrooted_python_sources_rules(),
            RootRule(HydratedTargets),
        )

    def make_hydrated_target(
        self, *, source_paths: List[str], type_alias: Optional[str] = None,
    ) -> HydratedTarget:
        adaptor = Mock()
        adaptor.type_alias = type_alias
        adaptor.sources = Mock()
        adaptor.sources.snapshot = self.make_snapshot({fp: "" for fp in source_paths})
        address = Address(
            spec_path=PurePath(source_paths[0]).parent.as_posix(), target_name="target"
        )
        adaptor.address = address
        return HydratedTarget(address=address, adaptor=adaptor, dependencies=())

    def test_adds_missing_inits_and_strips_source_roots(self) -> None:
        target_with_init = self.make_hydrated_target(
            source_paths=["src/python/project/lib.py", "src/python/project/__init__.py"],
        )
        target_without_init = self.make_hydrated_target(
            source_paths=["tests/python/test_project/f1.py", "tests/python/test_project/f2.py"],
        )
        files_target = self.make_hydrated_target(
            source_paths=["src/python/project/resources/loose_file.txt"], type_alias=Files.alias(),
        )
        result = self.request_single_product(
            ChrootedPythonSources,
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
