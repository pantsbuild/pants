# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading
from collections import defaultdict

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.address_lookup_error import AddressLookupError
from pants.base.exceptions import TaskError


class BootstrapJvmTools(IvyTaskMixin, Task):

  @classmethod
  def product_types(cls):
    return ['jvm_build_tools_classpath_callbacks']

  def execute(self):
    context = self.context
    if JvmToolTaskMixin.get_registered_tools():
      # Map of scope -> (map of key -> callback).
      callback_product_map = (context.products.get_data('jvm_build_tools_classpath_callbacks') or
                              defaultdict(dict))
      # We leave a callback in the products map because we want these Ivy calls
      # to be done lazily (they might never actually get executed) and we want
      # to hit Task.invalidated (called in Task.ivy_resolve) on the instance of
      # BootstrapJvmTools rather than the instance of whatever class requires
      # the bootstrap tools.  It would be awkward and possibly incorrect to call
      # self.invalidated twice on a Task that does meaningful invalidation on its
      # targets. -pl
      for scope, key in JvmToolTaskMixin.get_registered_tools():
        option = key.replace('-', '_')
        deplist = self.context.options.for_scope(scope)[option]
        callback_product_map[scope][key] = \
          self.cached_bootstrap_classpath_callback(key, scope, deplist)
      context.products.safe_create_data('jvm_build_tools_classpath_callbacks',
                                        lambda: callback_product_map)

  def _resolve_tool_targets(self, tools, key, scope):
    if not tools:
      raise TaskError("BootstrapJvmTools.resolve_tool_targets called with no tool"
                      " dependency addresses.  This probably means that you don't"
                      " have an entry in your pants.ini for this tool.")
    for tool in tools:
      try:
        targets = list(self.context.resolve(tool))
        if not targets:
          raise KeyError
      except (KeyError, AddressLookupError) as e:
        self.context.log.error("Failed to resolve target for tool: {tool}.\n"
                               "This target was obtained from option {option} in scope {scope}.\n"
                               "You probably need to add this target to your tools "
                               "BUILD file(s), usually located in the workspace root.\n"
                               "".format(tool=tool, e=e, scope=scope, option=key))
        raise TaskError()
      for target in targets:
        yield target

  def cached_bootstrap_classpath_callback(self, key, scope, tools):
    cache = {}
    cache_lock = threading.Lock()

    def bootstrap_classpath():
      with cache_lock:
        if 'classpath' not in cache:
          targets = list(self._resolve_tool_targets(tools, key, scope))
          workunit_name = 'bootstrap-{!s}'.format(key)
          cache['classpath'] = self.ivy_resolve(targets,
                                                silent=True,
                                                workunit_name=workunit_name)[0]
        return cache['classpath']
    return bootstrap_classpath
