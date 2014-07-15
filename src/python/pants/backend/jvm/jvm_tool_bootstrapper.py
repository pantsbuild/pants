# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.exceptions import TaskError


class JvmToolBootstrapper(object):

  def __init__(self, products):
    self._products = products

  def get_jvm_tool_classpath(self, key, executor=None):
    """Get a classpath for the tool previously registered under the key.

    Returns a list of paths.
    """
    return self.get_lazy_jvm_tool_classpath(key, executor)()

  def get_lazy_jvm_tool_classpath(self, key, executor=None):
    """Get a lazy classpath for the tool previously registered under the key.

    Returns a no-arg callable. Invoking it returns a list of paths.
    """
    callback_product_map = self._products.get_data('jvm_build_tools_classpath_callbacks') or {}
    callback = callback_product_map.get(key)
    if not callback:
      raise TaskError('No bootstrap callback registered for %s' % key)
    return lambda: callback(executor=executor)

  def register_jvm_tool(self, key, tools):
    """Register a list of targets against a key.

    We can later use this key to get a callback that will resolve these targets.
    Note: Not reentrant. We assume that all registration is done in the main thread.
    """
    if not tools:
      raise ValueError("No implementations were provided for tool '%s'" % key)
    self._products.require_data('jvm_build_tools_classpath_callbacks')
    tool_product_map = self._products.get_data('jvm_build_tools') or {}
    existing = tool_product_map.get(key)
    # It's OK to re-register with the same value, but not to change the value.
    if existing is not None:
      if existing != tools:
        raise TaskError('Attemping to change tools under %s from %s to %s.'
                        % (key, existing, tools))
    else:
      tool_product_map[key] = tools
      self._products.safe_create_data('jvm_build_tools', lambda: tool_product_map)
