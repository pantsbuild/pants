# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.contrib.python.checks.checker.plugin_test_base import CheckstylePluginTestBase

from pants.contrib.python.checks.checker.common import Nit
from pants.contrib.python.checks.checker.missing_contextmanager import MissingContextManager


class MissingContextManagerTest(CheckstylePluginTestBase):
    plugin_type = MissingContextManager

    def test_missing_contextmanager(self):
        statement = """
      with open("derp.txt"):
        pass

      with open("herp.txt") as fp:
        fp.read()
    """
        self.assertNoNits(statement)

        statement = """
      foo = open("derp.txt")
    """
        self.assertNit(statement, "T802", Nit.WARNING)

        # TODO(wickman): In these cases suggest using contextlib.closing.
        statement = """
      from urllib2 import urlopen
      the_googs = urlopen("http://www.google.com").read()
    """
        self.assertNoNits(statement)
