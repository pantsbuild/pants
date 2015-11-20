# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast

from pants.contrib.python.checks.tasks.checkstyle.common import CheckstylePlugin


# TODO(wickman)
#
# 1. open(foo) should always be done in a with context.
#
# 2. if you see acquire/release on the same variable in a particular ast
#    body, warn about context manager use.
class MissingContextManager(CheckstylePlugin):
  """Recommend the use of contextmanagers when it seems appropriate."""

  def nits(self):
    with_contexts = set(self.iter_ast_types(ast.With))
    with_context_calls = set(node.context_expr for node in with_contexts
        if isinstance(node.context_expr, ast.Call))

    for call in self.iter_ast_types(ast.Call):
      if isinstance(call.func, ast.Name) and call.func.id == 'open' \
        and (call not in with_context_calls):

        yield self.warning('T802', 'open() calls should be made within a contextmanager.', call)
