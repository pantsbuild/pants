# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.build_environment import pants_version
from pants.version import VERSION as _VERSION
from pants.testutil.test_base import TestBase


class PantsPluginPantsRequirementTest(TestBase):
  def test_version(self):
    self.assertEqual(pants_version(), _VERSION)
