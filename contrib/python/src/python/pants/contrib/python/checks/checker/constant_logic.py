# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast

from pants.contrib.python.checks.checker.common import CheckstylePlugin


class ConstantLogic(CheckstylePlugin):
  """Check for constants provided to and/or which will disregard the other operand's value."""

  @classmethod
  def name(cls):
    return 'constant-logic'

  @classmethod
  def iter_bool_ops(cls, tree):
    for ast_node in ast.walk(tree):
      if isinstance(ast_node, ast.BoolOp):
        if isinstance(ast_node.op, (ast.And, ast.Or)):
          yield ast_node

  @classmethod
  def is_probably_constant(cls, expr):
    if isinstance(expr, (ast.Num, ast.Str)):
      return True
    if isinstance(expr, ast.Name):
      if expr.id in ['True', 'False', 'None']:
        return True
    return False

  def nits(self):
    for bool_op in self.iter_bool_ops(self.python_file.tree):
      # We don't try to check anything in the middle of more complex logical expressions.
      leftmost = bool_op.values[0]
      rightmost = bool_op.values[-1]
      if self.is_probably_constant(leftmost):
        yield self.error('T804',
                         'Constant on left-hand side of a logical operator is probably an error.',
                         bool_op)
      if isinstance(bool_op.op, ast.And) and self.is_probably_constant(rightmost):
        yield self.error('T804',
                         'Constant on right-hand side of an and operator is probably an error.',
                         bool_op)
