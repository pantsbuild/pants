# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.contrib.python.checks.checker.plugin_test_base import CheckstylePluginTestBase

from pants.contrib.python.checks.checker.indentation import Indentation


class IndentationTest(CheckstylePluginTestBase):
    plugin_type = Indentation

    def test_indentation(self):
        statement = """
      def foo():
          pass
    """
        self.assertNit(statement, "T100")

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
