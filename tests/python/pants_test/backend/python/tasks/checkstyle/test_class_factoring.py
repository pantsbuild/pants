# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.class_factoring import ClassFactoring
from pants.backend.python.tasks.checkstyle.common import Nit
from pants_test.backend.python.tasks.checkstyle.plugin_test_base import CheckstylePluginTestBase


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
