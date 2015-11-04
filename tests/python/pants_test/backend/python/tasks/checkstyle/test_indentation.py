# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.indentation import Indentation
from pants_test.backend.python.tasks.checkstyle.plugin_test_base import CheckstylePluginTestBase


class IndentationTest(CheckstylePluginTestBase):
  plugin_type = Indentation

  def test_indentation(self):
    statement = """
      def foo():
          pass
    """
    self.assertNit(statement, 'T100')

    statement = """
      def foo():
        pass
    """
    self.assertNoNits(statement)

    statement = """
      def foo():
        baz = (
            "this "
            "is "
            "ok")
    """
    self.assertNoNits(statement)
