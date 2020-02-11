# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional
from unittest.mock import Mock

from pants.build_graph.address import Address
from pants.build_graph.files import Files
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.rules.core.strip_source_root import rules as strip_source_root_rules
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class StripSourceRootsTests(TestBase):
  @classmethod
  def rules(cls):
    return (*super().rules(), *strip_source_root_rules(), RootRule(HydratedTarget))

  def assert_stripped_source_file(
    self, *, original_path: str, expected_path: str, target_type_alias: Optional[str] = None,
  ) -> None:
    adaptor = Mock()
    adaptor.sources = Mock()
    adaptor.sources.snapshot = self.make_snapshot({original_path: "print('random python')"})
    adaptor.address = Mock()
    adaptor.address.spec_path = original_path
    if target_type_alias:
      adaptor.type_alias = target_type_alias
    target = HydratedTarget(Address.parse("some/target:target"), adaptor, ())
    stripped_sources = self.request_single_product(
      SourceRootStrippedSources, Params(target, create_options_bootstrapper())
    )
    self.assertEqual(stripped_sources.snapshot.files, (expected_path,))

  def test_source_roots_python(self):
    self.assert_stripped_source_file(
      original_path='src/python/pants/util/strutil.py', expected_path='pants/util/strutil.py',
    )

  def test_source_roots_java(self):
    self.assert_stripped_source_file(
      original_path='src/java/some/path/to/something.java',
      expected_path='some/path/to/something.java',
    )

  def test_dont_strip_source_for_files(self):
    self.assert_stripped_source_file(
        original_path='src/python/pants/util/strutil.py',
        expected_path='src/python/pants/util/strutil.py',
        target_type_alias=Files.alias()
    )
