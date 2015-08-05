# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.newlines import Newlines


TOPLEVEL = """
def foo():
  pass%s
%s
  pass
"""


def test_newlines():
  for toplevel_def in ('def bar():', 'class Bar(object):'):
    for num_newlines in (0, 1, 3, 4):
      newlines = Newlines(PythonFile.from_statement(TOPLEVEL % ('\n' * num_newlines, toplevel_def)))
      nits = list(newlines.nits())
      assert len(nits) == 1
      assert nits[0].code == 'T302'
      assert nits[0].severity == Nit.ERROR
    newlines = Newlines(PythonFile.from_statement(TOPLEVEL % ('\n\n', toplevel_def)))
    assert len(list(newlines.nits())) == 0


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


def test_classdefs():
  newlines = Newlines(PythonFile.from_statement(GOOD_CLASS_DEF_1))
  assert len(list(newlines.nits())) == 0

  newlines = Newlines(PythonFile.from_statement(GOOD_CLASS_DEF_2))
  assert len(list(newlines.nits())) == 0

  newlines = Newlines(PythonFile.from_statement(BAD_CLASS_DEF_1))
  nits = list(newlines.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T301'
  assert nits[0]._line_number == 4
  assert nits[0].severity == Nit.ERROR

  newlines = Newlines(PythonFile.from_statement(BAD_CLASS_DEF_2))
  nits = list(newlines.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T301'
  assert nits[0]._line_number == 7
  assert nits[0].severity == Nit.ERROR
