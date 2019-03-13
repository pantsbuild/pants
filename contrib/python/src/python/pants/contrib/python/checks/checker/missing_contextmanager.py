# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast

from six import PY3

from pants.contrib.python.checks.checker.common import CheckstylePlugin


# TODO(wickman)
#
# 1. open(foo) should always be done in a with context.
#
# 2. if you see acquire/release on the same variable in a particular ast
#    body, warn about context manager use.
class MissingContextManager(CheckstylePlugin):
  """Recommend the use of contextmanagers when it seems appropriate."""

  @classmethod
  def name(cls):
    return 'context-manager'

  def nits(self):
    with_contexts = set(self.iter_ast_types(ast.With))
    # Grammar changed between Python 2 vs Python 3 to access the with statement's surrounding expressions.
    # Refer to http://joao.npimentel.net/2015/07/23/python-2-vs-python-3-ast-differences/.
    with_context_exprs = ({node.context_expr for with_context in with_contexts for node in with_context.items}
                          if PY3 else
                          {node.context_expr for node in with_contexts})
    with_context_calls = {expr for expr in with_context_exprs if isinstance(expr, ast.Call)}

    for call in self.iter_ast_types(ast.Call):
      if isinstance(call.func, ast.Name) and call.func.id == 'open' \
        and (call not in with_context_calls):

        yield self.warning('T802', 'open() calls should be made within a contextmanager.', call)
