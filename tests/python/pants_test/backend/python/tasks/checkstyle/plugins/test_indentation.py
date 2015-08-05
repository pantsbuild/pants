# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.indentation import Indentation


def test_indentation():
  ind = Indentation(PythonFile.from_statement("""
    def foo():
        pass
  """))
  nits = list(ind.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T100'
  assert nits[0].severity == Nit.ERROR

  ind = Indentation(PythonFile.from_statement("""
    def foo():
      pass
  """))
  nits = list(ind.nits())
  assert len(nits) == 0

  ind = Indentation(PythonFile.from_statement("""
    def foo():
      baz = (
          "this "
          "is "
          "ok")
  """))
  nits = list(ind.nits())
  assert len(nits) == 0
