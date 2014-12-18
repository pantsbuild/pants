# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.jvm_tool_bootstrapper import JvmToolBootstrapper
from pants.option.options import Options


class JvmToolTaskMixin(object):

  _jvm_tool_bootstrapper = None
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

  @property
  def jvm_tool_bootstrapper(self):
    if self._jvm_tool_bootstrapper is None:
      self._jvm_tool_bootstrapper = JvmToolBootstrapper(self.context.new_options,
                                                        self.context.products)
    return self._jvm_tool_bootstrapper

  def tool_classpath(self, key, scope=None, executor=None):
    scope = scope or self.options_scope
    return self.jvm_tool_bootstrapper.get_jvm_tool_classpath(key, scope, executor)

  def lazy_tool_classpath(self, key, scope=None, executor=None):
    scope = scope or self.options_scope
    return self.jvm_tool_bootstrapper.get_lazy_jvm_tool_classpath(key, scope, executor)
