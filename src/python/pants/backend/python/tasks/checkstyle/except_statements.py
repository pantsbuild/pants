# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin
from pants.subsystem.subsystem import Subsystem


class ExceptStatementsSubsystem(Subsystem):
  options_scope = 'pycheck-except-statement'

  @classmethod
  def register_options(cls, register):
    super(ExceptStatementsSubsystem, cls).register_options(register)
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')


class ExceptStatements(CheckstylePlugin):
  """Do not allow non-3.x-compatible and/or dangerous except statements."""
  subsystem = ExceptStatementsSubsystem

  @classmethod
  def blanket_excepts(cls, node):
    for handler in node.handlers:
      if handler.type is None and handler.name is None:
        return handler

  @classmethod
  def iter_excepts(cls, tree):
    for ast_node in ast.walk(tree):
      if isinstance(ast_node, ast.TryExcept):
        yield ast_node

  def nits(self):
    for try_except in self.iter_excepts(self.python_file.tree):
      # Check case 1, blanket except
      handler = self.blanket_excepts(try_except)
      if handler:
        yield self.error('T803', 'Blanket except: not allowed.', handler)

      # Check case 2, except Foo, bar:
      for handler in try_except.handlers:
        statement = ''.join(self.python_file[handler.lineno])
        except_index = statement.index('except')
        except_suffix = statement[except_index + len('except'):]

        if handler.name and ' as ' not in except_suffix:
          yield self.error('T601', 'Old-style except statements forbidden.', handler)
