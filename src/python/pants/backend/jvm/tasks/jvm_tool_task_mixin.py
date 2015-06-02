# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.base.exceptions import TaskError


class JvmToolTaskMixin(JvmToolMixin):
  """A JvmToolMixin specialized for mixing in to Tasks."""

  class InvalidToolClasspath(TaskError):
    """Indicates an invalid jvm tool classpath."""

  def tool_jar(self, key, scope=None):
    """Get the jar for the tool previously registered under key in the given scope.

    :param string key: The key the tool configuration was registered under.
    :param string scope: The scope the tool configuration was registered under; the task scope by
                         default.
    :returns: A single jar path.
    :rtype: string
    :raises: `JvmToolTaskMixin.InvalidToolClasspath` when the tool classpath is not composed of
             exactly one jar.
    """
    scope = self._scope(scope)
    classpath = self.tool_classpath(key, scope=scope)
    if len(classpath) != 1:
      params = dict(tool=key, scope=scope, count=len(classpath), classpath='\n\t'.join(classpath))
      raise self.InvalidToolClasspath('Expected tool {tool} in scope {scope} to resolve to one '
                                      'jar, instead found {count}:\n\t{classpath}'.format(**params))
    return classpath[0]

  def tool_classpath(self, key, scope=None):
    """Get a classpath for the tool previously registered under key in the given scope.

    :param string key: The key the tool configuration was registered under.
    :param string scope: The scope the tool configuration was registered under; the task scope by
                         default.
    :returns: A list of paths.
    :rtype: list
    """
    return self.tool_classpath_from_products(self.context.products, key, scope=self._scope(scope))

  def _scope(self, scope=None):
    return scope or self.options_scope
