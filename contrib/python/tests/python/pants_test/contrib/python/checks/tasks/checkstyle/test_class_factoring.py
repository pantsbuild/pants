# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.class_factoring import ClassFactoring
from pants.contrib.python.checks.tasks.checkstyle.common import Nit


BAD_CLASS = """
class Distiller(object):
  CONSTANT = "foo"

  def foo(self, value):
    return os.path.join(Distiller.CONSTANT, value)
"""


class ClassFactoringTest(CheckstylePluginTestBase):
  plugin_type = ClassFactoring

  def test_class_factoring(self):
    self.assertNit(BAD_CLASS, 'T800', Nit.WARNING)
