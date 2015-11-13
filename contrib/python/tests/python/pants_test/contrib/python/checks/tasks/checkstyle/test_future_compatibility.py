# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.common import Nit, PythonFile
from pants.contrib.python.checks.tasks.checkstyle.future_compatibility import FutureCompatibility


BAD_CLASS = PythonFile.from_statement("""
class Distiller(object):
  CONSTANT = "foo"

  def foo(self, value):
    return os.path.join(Distiller.CONSTANT, value)
""")


class FutureCompatibilityTest(CheckstylePluginTestBase):
  plugin_type = FutureCompatibility

  def exemplar_fail(self, code, severity, statement):
    self.assertNit(statement, code, severity)

  def exemplar_pass(self, statement):
    self.assertNoNits(statement)

  def test_xrange(self):
    self.exemplar_fail('T603', Nit.ERROR, """
      for k in range(5):
        pass
      for k in xrange(10):
        pass
    """)

    self.exemplar_pass("""
      for k in obj.xrange(10):
        pass
    """)

  def test_iters(self):
    for function_name in FutureCompatibility.BAD_ITERS:
      self.exemplar_fail('T602', Nit.ERROR, """
        d = {1: 2, 2: 3, 3: 4}
        for k in d.%s():
          pass
        for k in d.values():
          pass
      """ % function_name)

  def test_names(self):
    for class_name in FutureCompatibility.BAD_NAMES:
      self.exemplar_fail('T604', Nit.ERROR, """
        if isinstance(k, %s):
          pass
        if isinstance(k, str):
          pass
      """ % class_name)

  def test_metaclass(self):
    self.exemplar_fail('T605', Nit.WARNING, """
      class Singleton(object):
        __metaclass__ = SingletonMetaclass
        CONSTANT = 2 + 3

        def __init__(self):
          pass
    """)
