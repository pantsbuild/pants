# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.checkstyle.print_statements import PrintStatements


def test_print_statements():
  ps = PrintStatements(PythonFile.from_statement("""
    from __future__ import print_function
    print("I do what I want")
    
    class Foo(object):
      def print(self):
        "I can do this because it's not a reserved word."
  """))
  assert len(list(ps.nits())) == 0

  ps = PrintStatements(PythonFile.from_statement("""
    print("I do what I want")
  """))
  assert len(list(ps.nits())) == 0

  ps = PrintStatements(PythonFile.from_statement("""
    print["I do what I want"]
  """))
  nits = list(ps.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T607'
  assert nits[0].severity == Nit.ERROR
