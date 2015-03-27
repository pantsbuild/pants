# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin


class JvmToolTaskMixin(JvmToolMixin):
  """A JvmToolMixin specialized for mixin in to Tasks."""

  def tool_classpath(self, key, scope=None):
    """Get a classpath for the tool previously registered under key in the given scope.

    Returns a list of paths.
    """
    return self.lazy_tool_classpath(key, scope=scope)()

  def lazy_tool_classpath(self, key, scope=None):
    """Get a lazy classpath for the tool previously registered under the key in the given scope.

    Returns a no-arg callable. Invoking it returns a list of paths.
    """
    return self.lazy_tool_classpath_from_products(self.context.products, key,
                                                  scope=scope or self.options_scope)
