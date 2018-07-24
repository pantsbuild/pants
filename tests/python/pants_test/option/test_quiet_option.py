# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.option.arg_splitter import GLOBAL_SCOPE
from pants_test.option.test_options import OptionsTestBase


class TestOptionsQuiet(OptionsTestBase):

  def _register(self, options):
    options.register(GLOBAL_SCOPE, '-q', '--quiet', type=bool, recursive=True)

  def test_recursive_quiet_deprecated(self):
    with self.stderr_catcher("Using the -q or --quiet option recursively") :
      options = self._parse('./pants run -q')
      self.assertEquals(True, options.for_global_scope().quiet)
