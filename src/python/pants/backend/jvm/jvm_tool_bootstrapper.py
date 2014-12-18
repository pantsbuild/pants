# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.exceptions import TaskError


class JvmToolBootstrapper(object):

  def __init__(self, products):
    self._products = products

  def get_jvm_tool_classpath(self, key, scope, executor=None):
    """Get a classpath for the tool previously registered under key in the given scope.

    Returns a list of paths.
    """
    return self.get_lazy_jvm_tool_classpath(key, scope, executor)()

  def get_lazy_jvm_tool_classpath(self, key, scope, executor=None):
    """Get a lazy classpath for the tool previously registered under the key in the given scope.

    Returns a no-arg callable. Invoking it returns a list of paths.
    """
    callback_product_map = self._products.get_data('jvm_build_tools_classpath_callbacks') or {}
    callback = callback_product_map.get(scope, {}).get(key)
    if not callback:
      raise TaskError('No bootstrap callback registered for {key} in {scope}'.format(
        key=key, scope=scope))
    return lambda: callback(executor=executor)
