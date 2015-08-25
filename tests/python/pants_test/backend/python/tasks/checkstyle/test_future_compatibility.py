# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.checkstyle.future_compatibility import FutureCompatibility


BAD_CLASS = PythonFile.from_statement("""
class Distiller(object):
  CONSTANT = "foo"

  def foo(self, value):
    return os.path.join(Distiller.CONSTANT, value)
""")


def exemplar_fail(code, severity, statement):
  nits = list(FutureCompatibility(PythonFile.from_statement(statement)).nits())
  assert len(nits) == 1
  assert nits[0].code == code
  assert nits[0].severity == severity
  return nits[0]


def exemplar_pass(statement):
  nits = list(FutureCompatibility(PythonFile.from_statement(statement)).nits())
  assert len(nits) == 0


def test_xrange():
  exemplar_fail('T603', Nit.ERROR, """
    for k in range(5):
      pass
    for k in xrange(10):
      pass
  """)

  exemplar_pass("""
    for k in obj.xrange(10):
      pass
  """)


def test_iters():
  for function_name in FutureCompatibility.BAD_ITERS:
    exemplar_fail('T602', Nit.ERROR, """
      d = {1: 2, 2: 3, 3: 4}
      for k in d.%s():
        pass
      for k in d.values():
        pass
    """ % function_name)


def test_names():
  for class_name in FutureCompatibility.BAD_NAMES:
    exemplar_fail('T604', Nit.ERROR, """
      if isinstance(k, %s):
        pass
      if isinstance(k, str):
        pass
    """ % class_name)


def test_metaclass():
  exemplar_fail('T605', Nit.WARNING, """
    class Singleton(object):
      __metaclass__ = SingletonMetaclass
      CONSTANT = 2 + 3

      def __init__(self):
        pass
  """)
