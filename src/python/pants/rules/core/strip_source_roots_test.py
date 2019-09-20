# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from unittest.mock import Mock

from pants.engine.fs import create_fs_rules
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.strip_source_root import SourceRootStrippedSources, strip_source_root
from pants.source.source_root import SourceRootConfig
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.test_base import TestBase


class StripSourceRootsTests(TestBase):
  @classmethod
  def rules(cls):
    return super().rules() + [
      strip_source_root,
      RootRule(SourceRootConfig),
      RootRule(HydratedTarget),
    ] + create_fs_rules()

  def mock_hydrated_target(self, target_address, source_filename):
    adaptor = Mock()
    adaptor.sources = Mock()
    source_files = dict()
    source_files[source_filename] = "print('random python')"
    adaptor.sources.snapshot = self.make_snapshot(source_files)
    adaptor.address = Mock()
    adaptor.address.spec_path = source_filename
    return HydratedTarget(target_address, adaptor, tuple())

  def test_source_roots(self):
    init_subsystem(SourceRootConfig)
    target = self.mock_hydrated_target("some/target/address", 'src/python/pants/util/strutil.py')
    output = self.scheduler.product_request(SourceRootStrippedSources, [Params(target, SourceRootConfig.global_instance())])
    stripped_sources = output[0]
    self.assertEqual(stripped_sources.snapshot.files, ('pants/util/strutil.py',))

  def test_source_roots_java(self):
    init_subsystem(SourceRootConfig)
    target = self.mock_hydrated_target("some/target/address", 'src/java/some/path/to/something.java')
    output = self.scheduler.product_request(SourceRootStrippedSources, [Params(target, SourceRootConfig.global_instance())])
    stripped_sources = output[0]
    self.assertEqual(stripped_sources.snapshot.files, ('some/path/to/something.java',))
