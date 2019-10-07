# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast
import re

from six import PY3

from pants.contrib.python.checks.checker.common import CheckstylePlugin


class PrintStatements(CheckstylePlugin):
  """Enforce the use of print as a function and not a statement."""

  @classmethod
  def name(cls):
    return 'print-statements'

  FUNCTIONY_EXPRESSION = re.compile(r'^\s*\(.*\)\s*$')

  def nits(self):
    if PY3:
      # Python 3 interpreter will raise SyntaxError upon reading a print statement.
      # So, this module cannot be meaningfully used when ran with a Python 3 interpreter.
      return
    for print_stmt in self.iter_ast_types(ast.Print):
      # In Python 3.x and in 2.x with __future__ print_function, prints show up as plain old
      # function expressions.  ast.Print does not exist in Python 3.x.  However, allow use
      # syntactically as a function, i.e. ast.Print but with ws "(" .* ")" ws
      logical_line = ''.join(self.python_file[print_stmt.lineno])
      print_offset = logical_line.index('print')
      stripped_line = logical_line[print_offset + len('print'):]
      if not self.FUNCTIONY_EXPRESSION.match(stripped_line):
        yield self.error('T607', 'Print used as a statement.', print_stmt)
