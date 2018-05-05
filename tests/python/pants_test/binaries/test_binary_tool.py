# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import mock

from pants.binaries.binary_tool import BinaryToolBase, NativeTool, Script
from pants_test.base_test import BaseTest
# from pants_test.binaries.test_binary_util import


class SomeDefaultUrlsGenerationTODO(BinaryToolBase): pass


class DefaultVersion(BinaryToolBase):
  options_scope = 'default-version-test'
  name = 'default_version_test_tool'
  default_version = 'XXX'


class BinaryToolBaseTest(BaseTest):

  def test_base_options(self):
    # TODO: using extra_version_option_kwargs!
    pass
