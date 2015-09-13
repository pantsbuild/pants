# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import re

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin
from pants.subsystem.subsystem import Subsystem


class PrintStatementsSubsystem(Subsystem):
  options_scope = 'pycheck-print-statements'

  @classmethod
  def register_options(cls, register):
    super(PrintStatementsSubsystem, cls).register_options(register)
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')


class PrintStatements(CheckstylePlugin):
  """Enforce the use of print as a function and not a statement."""

  FUNCTIONY_EXPRESSION = re.compile(r'^\s*\(.*\)\s*$')
  subsystem = PrintStatementsSubsystem

  def nits(self):
    for print_stmt in self.iter_ast_types(ast.Print):
      # In Python 3.x and in 2.x with __future__ print_function, prints show up as plain old
      # function expressions.  ast.Print does not exist in Python 3.x.  However, allow use
      # syntactically as a function, i.e. ast.Print but with ws "(" .* ")" ws
      logical_line = ''.join(self.python_file[print_stmt.lineno])
      print_offset = logical_line.index('print')
      stripped_line = logical_line[print_offset + len('print'):]
      if not self.FUNCTIONY_EXPRESSION.match(stripped_line):
        yield self.error('T607', 'Print used as a statement.', print_stmt)
