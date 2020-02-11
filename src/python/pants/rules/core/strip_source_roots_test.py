# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from functools import partial
from typing import List, Optional, Union
from unittest.mock import Mock

import pytest

from pants.build_graph.files import Files
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import RootRule
from pants.engine.scheduler import ExecutionError
from pants.engine.selectors import Params
from pants.rules.core.strip_source_roots import SnapshotToStrip, SourceRootStrippedSources
from pants.rules.core.strip_source_roots import rules as strip_source_root_rules
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class StripSourceRootsTests(TestBase):
  @classmethod
  def rules(cls):
    return (
      *super().rules(),
      *strip_source_root_rules(),
      RootRule(HydratedTarget),
      RootRule(SnapshotToStrip),
    )

  def get_stripped_files(
    self, original: Union[SnapshotToStrip, HydratedTarget], *, args: Optional[List[str]] = None,
  ) -> List[str]:
    result = self.request_single_product(
      SourceRootStrippedSources, Params(original, create_options_bootstrapper(args=args))
    )
    return sorted(result.snapshot.files)

  def test_strip_snapshot(self) -> None:
    original_paths = [
      "src/python/project/example.py",
      "src/java/com/project/example.java",
      "tests/python/project_test/example.py",
      "no-source-root/example.txt",
    ]
    stripped_paths = [
      "project/example.py",
      "com/project/example.java",
      "project_test/example.py",
      "example.txt",
    ]

    input_snapshot = self.make_snapshot({fp: "" for fp in original_paths})
    get_stripped_files_for_snapshot = partial(
      self.get_stripped_files, SnapshotToStrip(input_snapshot)
    )

    assert get_stripped_files_for_snapshot() == sorted(stripped_paths)

    # Also test that we error when `--source-unmatched=fail`
    with pytest.raises(ExecutionError) as exc:
      get_stripped_files_for_snapshot(args=["--source-unmatched=fail"])
    assert "NoSourceRootError: Could not find a source root for `no-source-root/example.txt`" in str(exc.value)

  def test_strip_target(self) -> None:

    def get_stripped_files_for_target(
      *, source_paths: Optional[List[str]], type_alias: Optional[str] = None,
    ) -> List[str]:
      adaptor = Mock()
      adaptor.type_alias = type_alias

      if source_paths is None:
        del adaptor.sources
        return self.get_stripped_files(
          HydratedTarget(address=Mock(), adaptor=adaptor, dependencies=()),
        )

      adaptor.sources = Mock()
      adaptor.sources.snapshot = self.make_snapshot({fp: "" for fp in source_paths})

      return self.get_stripped_files(
        HydratedTarget(address=Mock(), adaptor=adaptor, dependencies=()),
      )

    # normal target
    assert get_stripped_files_for_target(
      source_paths=["src/python/project/f1.py", "src/python/project/f2.py"]
    ) == sorted(["project/f1.py", "project/f2.py"])

    # empty target
    assert get_stripped_files_for_target(source_paths=None) == []

    # files targets are not stripped
    assert get_stripped_files_for_target(
      source_paths=["src/python/project/f1.py"], type_alias=Files.alias(),
    ) == ["src/python/project/f1.py"]
