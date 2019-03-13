# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast

from six import PY3

from pants.contrib.python.checks.checker.common import CheckstylePlugin


class ConstantLogic(CheckstylePlugin):
  """Check for constants provided to boolean operators which result in a constant expression."""

  @classmethod
  def name(cls):
    return 'constant-logic'

  @classmethod
  def iter_bool_ops(cls, tree):
    for ast_node in ast.walk(tree):
      if isinstance(ast_node, ast.BoolOp) and isinstance(ast_node.op, (ast.And, ast.Or)):
        yield ast_node

  @classmethod
  def is_name_constant(cls, expr):
    if PY3:
      if isinstance(expr, ast.NameConstant):
        return True
    else:
      if isinstance(expr, ast.Name) and expr.id in ['True', 'False', 'None']:
        return True
    return False

  @classmethod
  def is_probably_constant(cls, expr):
    if isinstance(expr, (ast.Num, ast.Str)):
      return True
    if cls.is_name_constant(expr):
      return True
    return False

  def nits(self):
    for bool_op in self.iter_bool_ops(self.python_file.tree):
      # We don't try to check anything in the middle of logical expressions with more than two
      # values.
      leftmost = bool_op.values[0]
      rightmost = bool_op.values[-1]
      if self.is_probably_constant(leftmost):
        yield self.error('T804',
                         'You are using a constant on the left-hand side of a logical operator. '
                         'This is probably an error.',
                         bool_op)
      if isinstance(bool_op.op, ast.And) and self.is_probably_constant(rightmost):
        yield self.error('T805',
                         'You are using a constant on the right-hand side of an `and` operator. '
                         'This is probably an error.',
                         bool_op)
