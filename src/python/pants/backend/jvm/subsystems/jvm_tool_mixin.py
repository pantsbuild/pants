# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TaskError
from pants.option.options import Options


class JvmToolMixin(object):
  """A mixin for registering and accessing JVM-based tools."""

  _tool_keys = []  # List of (scope, key) pairs.

  @classmethod
  def register_jvm_tool(cls, register, key, default=None):
    """Register a tool."""
    register('--{0}'.format(key),
             advanced=True,
             type=Options.list,
             default=default or ['//:{0}'.format(key)],
             help='Target specs for bootstrapping the {0} tool.'.format(key))
    JvmToolMixin._tool_keys.append((register.scope, key))

  @staticmethod
  def get_registered_tools():
    return JvmToolMixin._tool_keys

  @staticmethod
  def reset_registered_tools():
    """Needed only for test isolation."""
    JvmToolMixin._tool_keys = []

  def tool_classpath_from_products(self, products, key, scope):
    """Get a classpath for the tool previously registered under key in the given scope.

    Returns a list of paths.
    """
    return self.lazy_tool_classpath_from_products(products, key, scope)()

  def lazy_tool_classpath_from_products(self, products, key, scope):
    """Get a lazy classpath for the tool previously registered under the key in the given scope.

    Returns a no-arg callable. Invoking it returns a list of paths.
    """
    callback_product_map = products.get_data('jvm_build_tools_classpath_callbacks') or {}
    callback = callback_product_map.get(scope, {}).get(key)
    if not callback:
      raise TaskError('No bootstrap callback registered for {key} in {scope}'.format(
        key=key, scope=scope))
    return callback
