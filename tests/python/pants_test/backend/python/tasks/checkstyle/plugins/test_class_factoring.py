# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.checkstyle.plugins.class_factoring import ClassFactoring


BAD_CLASS = PythonFile.from_statement("""
class Distiller(object):
  CONSTANT = "foo"

  def foo(self, value):
    return os.path.join(Distiller.CONSTANT, value)
""")


def test_class_factoring():
  plugin = ClassFactoring(BAD_CLASS)
  nits = list(plugin.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T800'
  assert nits[0].severity == Nit.WARNING
