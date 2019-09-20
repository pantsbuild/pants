# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.legacy.structs import TargetAdaptor, PythonBinaryAdaptor, PythonTestsAdaptor
from pants.rules.core.strip_source_root import SourceRootStrippedSources, strip_source_root
from pants.engine.rules import optionable_rule, RootRule
from pants.engine.selectors import Get, Params
from pants_test.test_base import TestBase
from pants.source.source_root import SourceRootConfig

from unittest.mock import Mock
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants_test.subsystem.subsystem_util import init_subsystem
from pants.engine.fs import EMPTY_SNAPSHOT, Digest, DirectoryWithPrefixToStrip, Snapshot, create_fs_rules



class StripSourceRootsTests(TestBase):
  @classmethod
  def rules(cls):
    return super().rules() + [
      strip_source_root,
      optionable_rule(SourceRootConfig),
      RootRule(SourceRootConfig),
    ] + create_fs_rules()

  def test_source_roots(self):

    init_subsystem(SourceRootConfig)

    adaptor = PythonTestsAdaptor(type_alias='python_tests')
    target = HydratedTarget(Address.parse("some/target"), adaptor, ())

    output = self.scheduler.product_request(SourceRootStrippedSources, [Params(target, SourceRootConfig.global_instance())])

    print(f"Output: {output}")
    self.assertEqual(1, 1)
    self.assertEqual(output, 5)

