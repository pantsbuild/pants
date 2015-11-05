# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit
from pants.backend.python.tasks.checkstyle.missing_contextmanager import MissingContextManager
from pants_test.backend.python.tasks.checkstyle.plugin_test_base import CheckstylePluginTestBase


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
    self.assertNit(statement, 'T802', Nit.WARNING)

    # TODO(wickman): In these cases suggest using contextlib.closing.
    statement = """
      from urllib2 import urlopen
      the_googs = urlopen("http://www.google.com").read()
    """
    self.assertNoNits(statement)
