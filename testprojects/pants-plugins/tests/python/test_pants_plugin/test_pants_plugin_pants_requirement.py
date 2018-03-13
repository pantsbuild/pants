# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.build_environment import pants_version
from pants.version import VERSION as _VERSION
from pants_test.base_test import BaseTest


class PantsPluginPantsRequirementTest(BaseTest):
  def test_version(self):
    self.assertEqual(pants_version(), _VERSION)
