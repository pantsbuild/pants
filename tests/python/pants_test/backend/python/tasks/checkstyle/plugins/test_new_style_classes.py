# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.checkstyle.plugins.new_style_classes import NewStyleClasses


def test_new_style_classes():
  nsc = NewStyleClasses(PythonFile.from_statement("""
    class OldStyle:
      pass
    
    class NewStyle(object):
      pass
  """))
  nits = list(nsc.nits())
  assert len(nits) == 1
  assert nits[0]._line_number == 1
  assert nits[0].code == 'T606'
  assert nits[0].severity == Nit.ERROR

  nsc = NewStyleClasses(PythonFile.from_statement("""
    class NewStyle(OtherThing, ThatThing, WhatAmIDoing):
      pass
  """))
  nits = list(nsc.nits())
  assert len(nits) == 0

  nsc = NewStyleClasses(PythonFile.from_statement("""
    class OldStyle():  # unspecified mro
      pass
  """))
  nits = list(nsc.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T606'
