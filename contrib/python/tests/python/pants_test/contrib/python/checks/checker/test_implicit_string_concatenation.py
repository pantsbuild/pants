# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.contrib.python.checks.checker.plugin_test_base import CheckstylePluginTestBase

from pants.contrib.python.checks.checker.common import Nit
from pants.contrib.python.checks.checker.implicit_string_concatenation import \
  ImplicitStringConcatenation


class ImplicitStringConcatenationTest(CheckstylePluginTestBase):
  plugin_type = ImplicitStringConcatenation

  def test_implicit_string_concatenation(self):
    self.assertNit("'a' 'b'", 'T806', Nit.WARNING)
    self.assertNit('"a" "b"', 'T806', Nit.WARNING)
    self.assertNit("'a' \"b\"", 'T806', Nit.WARNING)
    self.assertNit("('a'\n'b')", 'T806', Nit.WARNING)
    self.assertNit("('a''b')", 'T806', Nit.WARNING)
    self.assertNit("'a''b'", 'T806', Nit.WARNING)
    self.assertNoNits("'a' + 'b'")
    self.assertNoNits("('a' + 'b')")
    self.assertNoNits("'''hello!'''")
    self.assertNoNits('"""hello"""')
