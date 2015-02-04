# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.exceptions import TaskError
from pants.option.options import Options


class JvmToolTaskMixin(object):

  _tool_keys = []  # List of (scope, key) pairs.

  @classmethod
  def register_jvm_tool(cls, register, key, default=None):
    register('--{0}'.format(key),
             type=Options.list,
             default=default or ['//:{0}'.format(key)],
             help='Target specs for bootstrapping the {0} tool.'.format(key))
    JvmToolTaskMixin._tool_keys.append((cls.options_scope, key))

  @staticmethod
  def get_registered_tools():
    return JvmToolTaskMixin._tool_keys

  @staticmethod
  def reset_registered_tools():
    """Needed only for test isolation."""
    JvmToolTaskMixin._tool_keys = []

  def tool_classpath(self, key, scope=None):
    """Get a classpath for the tool previously registered under key in the given scope.

    Returns a list of paths.
    """
    return self.lazy_tool_classpath(key, scope)()

  def lazy_tool_classpath(self, key, scope=None):
    """Get a lazy classpath for the tool previously registered under the key in the given scope.

    Returns a no-arg callable. Invoking it returns a list of paths.
    """
    scope = scope or self.options_scope
    callback_product_map = \
      self.context.products.get_data('jvm_build_tools_classpath_callbacks') or {}
    callback = callback_product_map.get(scope, {}).get(key)
    if not callback:
      raise TaskError('No bootstrap callback registered for {key} in {scope}'.format(
        key=key, scope=scope))
    return callback
