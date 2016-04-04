# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.newlines import Newlines


class NewlinesTest(CheckstylePluginTestBase):
  plugin_type = Newlines

  TOPLEVEL = """
  def foo():
    pass{}
  {}
    pass
  """

  def test_newlines(self):
    for toplevel_def in ('def bar():', 'class Bar(object):'):
      for num_newlines in (0, 1, 3, 4):
        statement = self.TOPLEVEL.format('\n' * num_newlines, toplevel_def)
        self.assertNit(statement, 'T302')
      statement = self.TOPLEVEL.format('\n\n', toplevel_def)
      self.assertNoNits(statement)

  GOOD_CLASS_DEF_1 = """
  class Foo(object):
    def __init__(self):
      pass

    def bar(self):
      pass
  """

  GOOD_CLASS_DEF_2 = """
  class Foo(object):
    def __init__(self):
      pass

    # this should be fine
    def bar(self):
      pass
  """

  GOOD_CLASS_DEF_3 = """
  class Foo(object):
    class Error(Exception): pass
    class SomethingError(Error): pass

    def __init__(self):
      pass

    def bar(self):
      pass
  """

  BAD_CLASS_DEF_1 = """
  class Foo(object):
    class Error(Exception): pass
    class SomethingError(Error): pass
    def __init__(self):
      pass

    def bar(self):
      pass
  """

  BAD_CLASS_DEF_2 = """
  class Foo(object):
    class Error(Exception): pass
    class SomethingError(Error): pass

    def __init__(self):
      pass
    def bar(self):
      pass
  """

  def test_classdefs(self):
    self.assertNoNits(self.GOOD_CLASS_DEF_1)
    self.assertNoNits(self.GOOD_CLASS_DEF_2)
    self.assertNit(self.BAD_CLASS_DEF_1, 'T301', expected_line_number='004')
    self.assertNit(self.BAD_CLASS_DEF_2, 'T301', expected_line_number='007')
