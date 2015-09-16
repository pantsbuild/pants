# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.task import TaskBase
from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin


class JvmToolTaskMixin(JvmToolMixin, TaskBase):
  """A JvmToolMixin specialized for mixing in to Tasks."""

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmToolTaskMixin, cls).prepare(options, round_manager)
    cls.prepare_tools(round_manager)

  def tool_jar(self, key, scope=None):
    """Get the jar for the tool previously registered under key in the given scope.

    :param string key: The key the tool configuration was registered under.
    :param string scope: The scope the tool configuration was registered under; the task scope by
                         default.
    :returns: A single jar path.
    :rtype: string
    :raises: `JvmToolMixin.InvalidToolClasspath` when the tool classpath is not composed of exactly
             one jar.
    """
    return self.tool_jar_from_products(self.context.products, key, scope=self._scope(scope))

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
