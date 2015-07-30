# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.checkstyle.plugins.trailing_whitespace import TrailingWhitespace


def test_exception_map():
  tw = TrailingWhitespace(PythonFile.from_statement("""
  test_string_001 = ""
  test_string_002 = " "
  test_string_003 = \"\"\"  
    foo   
  \"\"\"
  test_string_006 = ("   "
                     "   ")
  class Foo(object):
    pass
  # comment 010  
  test_string_011 = ''
  # comment 012
  # comment 013
  """))
  assert len(list(tw.nits())) == 0
  assert not tw.has_exception(9, 0, 0)
  assert not tw.has_exception(3, 0, 1)
  assert not tw.has_exception(3, 17, 17)
  assert tw.has_exception(3, 18, 18)
  assert tw.has_exception(3, 18, 10000)  # """ continuated strings have no ends. 
  assert not tw.has_exception(6, 8, 8)
  assert tw.has_exception(6, 19, 19)
  assert tw.has_exception(6, 19, 23)
  assert not tw.has_exception(6, 23, 25)  # ("  " continuations have string termination


def test_continuation_with_exception():
  tw = TrailingWhitespace(PythonFile.from_statement("""
  test_string_001 = ("   "  
                     "   ")
  """))
  nits = list(tw.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T200'
  assert nits[0].severity == Nit.ERROR


def test_trailing_slash():
  tw = TrailingWhitespace(PythonFile.from_statement("""
  foo = \\
    123
  bar = \"\"\"
    bin/bash foo \\
             bar \\
             baz
  \"\"\"
  """))
  nits = list(tw.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T201'
  assert nits[0].severity == Nit.ERROR
  assert nits[0]._line_number == 1
