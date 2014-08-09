# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import threading

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit


class BootstrapJvmTools(Task, IvyTaskMixin):

  @classmethod
  def product_types(cls):
    return ['jvm_build_tools_classpath_callbacks']

  def __init__(self, *args, **kwargs):
    super(BootstrapJvmTools, self).__init__(*args, **kwargs)

  def prepare(self, round_manager):
    # TODO(John Sirois): This is the sole use of data dependencies that does not follow the phase
    # lifecycle.  The BootstrapJvmTools task must execute before all JVM tool using tasks but
    # the 'jvm_build_tools' "data" must be produced by each JVM tool using task before it executes.
    # Normally data dependencies flow between task executions. Untangle this data dependency abuse.
    # One idea is to leverage rounds and have each JVM tool using task require a 'runtime_classpath'
    # for a restricted target graph which is just comprised of the tool dependency specs.  This
    # should allow killing BootstrapJvmTools outright - IvyResolve will do the job in the sub-round
    # and all standard caching will apply.

    # NB: commented out because this is an unsatisfiable dep under strict checks of proper ordering.
    #round_manager.require_data('jvm_build_tools')
    pass

  def execute(self):
    context = self.context
    if context.products.is_required_data('jvm_build_tools_classpath_callbacks'):
      tool_product_map = context.products.get_data('jvm_build_tools') or {}
      callback_product_map = context.products.get_data('jvm_build_tools_classpath_callbacks') or {}
      # We leave a callback in the products map because we want these Ivy calls
      # to be done lazily (they might never actually get executed) and we want
      # to hit Task.invalidated (called in Task.ivy_resolve) on the instance of
      # BootstrapJvmTools rather than the instance of whatever class requires
      # the bootstrap tools.  It would be awkward and possibly incorrect to call
      # self.invalidated twice on a Task that does meaningful invalidation on its
      # targets. -pl
      for key, deplist in tool_product_map.iteritems():
        callback_product_map[key] = self.cached_bootstrap_classpath_callback(key, deplist)
      context.products.safe_create_data('jvm_build_tools_classpath_callbacks',
                                        lambda: callback_product_map)

  def resolve_tool_targets(self, tools):
    if not tools:
      raise TaskError("BootstrapJvmTools.resolve_tool_targets called with no tool"
                      " dependency addresses.  This probably means that you don't"
                      " have an entry in your pants.ini for this tool.")
    for tool in tools:
      try:
        targets = list(self.context.resolve(tool))
        if not targets:
          raise KeyError
      except KeyError:
        self.context.log.error("Failed to resolve target for bootstrap tool: %s. "
                               "You probably need to add this dep to your tools "
                               "BUILD file(s), usually located in the root of the build." %
                               tool)
        raise
      for target in targets:
        yield target

  def cached_bootstrap_classpath_callback(self, key, tools):
    cache = {}
    cache_lock = threading.Lock()

    def bootstrap_classpath(executor=None):
      with cache_lock:
        if 'classpath' not in cache:
          targets = list(self.resolve_tool_targets(tools))
          workunit_name = 'bootstrap-%s' % str(key)
          cache['classpath'] = self.ivy_resolve(targets,
                                                executor=executor,
                                                silent=True,
                                                workunit_name=workunit_name,
                                                workunit_labels=[WorkUnit.BOOTSTRAP])
        return cache['classpath']
    return bootstrap_classpath
