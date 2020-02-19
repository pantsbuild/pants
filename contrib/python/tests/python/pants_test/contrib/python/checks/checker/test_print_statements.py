# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants_test.contrib.python.checks.checker.plugin_test_base import CheckstylePluginTestBase

from pants.contrib.python.checks.checker.print_statements import PrintStatements


class PrintStatementsTest(CheckstylePluginTestBase):
    plugin_type = PrintStatements

    def test_print_override(self):
        statement = """
      from __future__ import print_function
      print("I do what I want")

      class Foo(object):
        def print(self):
          "I can do this because it's not a reserved word."
    """
        self.assertNoNits(statement)

    def test_print_function(self):
        statement = """
      print("I do what I want")
    """
        self.assertNoNits(statement)

    @unittest.skip(reason="#7979: Rework tests so that we can run this with Python 2.")
    def test_print_statement(self):
        statement = """
      print["I do what I want"]
    """
        self.assertNit(statement, "T607")
