# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import List, Optional, Union
from unittest.mock import Mock

import pytest

from pants.build_graph.address import Address
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

    def get_stripped_files_for_snapshot(
      paths: List[str], *, args: Optional[List[str]] = None
    ) -> List[str]:
      input_snapshot = self.make_snapshot({fp: "" for fp in paths})
      return self.get_stripped_files(
        SnapshotToStrip(input_snapshot, sentinel_file=paths[0]), args=args,
      )

    # Normal source roots
    assert get_stripped_files_for_snapshot(
      ["src/python/project/example.py"]
    ) == ["project/example.py"]
    assert get_stripped_files_for_snapshot(
      ["src/java/com/project/example.java"]
    ) == ["com/project/example.java"]
    assert get_stripped_files_for_snapshot(
      ["tests/python/project_test/example.py"]
    ) == ["project_test/example.py"]

    # Unrecognized source root
    unrecognized_source_root = "no-source-root/example.txt"
    assert get_stripped_files_for_snapshot([unrecognized_source_root]) == ["example.txt"]
    with pytest.raises(ExecutionError) as exc:
      get_stripped_files_for_snapshot([unrecognized_source_root], args=["--source-unmatched=fail"])
    assert f"NoSourceRootError: Could not find a source root for `{unrecognized_source_root}`" in str(exc.value)

    # We don't support multiple source roots in the same snapshot, but also don't proactively
    # validate for this situation because we don't expect it to happen in practice and we want to
    # avoid having to call `SourceRoot.find_by_path` on every single file.
    with pytest.raises(ExecutionError) as exc:
      get_stripped_files_for_snapshot(
        ["src/python/project/example.py", "src/java/com/project/example.java"],
      )
    assert "Cannot strip prefix src/python" in str(exc.value)

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

      address = Address(spec_path=PurePath(source_paths[0]).parent.as_posix(), target_name="target")
      return self.get_stripped_files(
        HydratedTarget(address=address, adaptor=adaptor, dependencies=()),
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
