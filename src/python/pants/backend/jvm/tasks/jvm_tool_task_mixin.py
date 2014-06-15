# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.jvm_tool_bootstrapper import JvmToolBootstrapper


class JvmToolTaskMixin(object):

  _jvm_tool_bootstrapper = None
  @property
  def jvm_tool_bootstrapper(self):
    if self._jvm_tool_bootstrapper is None:
      self._jvm_tool_bootstrapper = JvmToolBootstrapper(self.context.products)
    return self._jvm_tool_bootstrapper

  def register_jvm_tool(self, key, target_addrs):
    self.jvm_tool_bootstrapper.register_jvm_tool(key, target_addrs)

  def tool_classpath(self, key, executor=None):
    return self.jvm_tool_bootstrapper.get_jvm_tool_classpath(key, executor)

  def lazy_tool_classpath(self, key, executor=None):
    return self.jvm_tool_bootstrapper.get_lazy_jvm_tool_classpath(key, executor)

