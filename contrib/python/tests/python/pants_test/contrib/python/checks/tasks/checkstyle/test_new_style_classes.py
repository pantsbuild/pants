# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.new_style_classes import NewStyleClasses


class NewStyleClassesTest(CheckstylePluginTestBase):
  plugin_type = NewStyleClasses

  def test_new_style_classes(self):
    statement = """
      class OldStyle:
        pass

      class NewStyle(object):
        pass
    """
    self.assertNit(statement, 'T606')

    statement = """
      class NewStyle(OtherThing, ThatThing, WhatAmIDoing):
        pass
    """
    self.assertNoNits(statement)

    statement = """
      class OldStyle():  # unspecified mro
        pass
    """
    self.assertNit(statement, 'T606')
