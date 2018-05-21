# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.global_options import GlobMatchErrorBehavior
from pants_test.base_test import BaseTest


class GlobalOptionsTest(BaseTest):

  def test_exception_glob_match_constructor(self):
    # NB: 'allow' is not a valid value for GlobMatchErrorBehavior.
    with self.assertRaises(TypeError) as cm:
      GlobMatchErrorBehavior(str('allow'))
    expected_msg = (
      """error: in constructor of type GlobMatchErrorBehavior: type check error:
Value 'allow' for failure_behavior must be one of: [u'ignore', u'warn', u'error'].""")
    self.assertEqual(str(cm.exception), expected_msg)
