# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.indentation import Indentation


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
