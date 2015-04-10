# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os
import shutil
import threading
from collections import defaultdict

from pants.backend.jvm.tasks.ivy_task_mixin import IvyResolveFingerprintStrategy, IvyTaskMixin
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.address_lookup_error import AddressLookupError
from pants.base.exceptions import TaskError
from pants.java import util
from pants.java.executor import Executor
from pants.java.jar.shader import Shader
from pants.util.dirutil import safe_mkdir_for


class ShadedToolFingerprintStrategy(IvyResolveFingerprintStrategy):
  def __init__(self, key, scope, main, custom_rules=None):
    # The bootstrapper uses no custom confs in its resolves.
    super(ShadedToolFingerprintStrategy, self).__init__(confs=None)

    self._key = key
    self._scope = scope
    self._main = main
    self._custom_rules = custom_rules

  def compute_fingerprint(self, target):
    hasher = hashlib.sha1()
    base_fingerprint = super(ShadedToolFingerprintStrategy, self).compute_fingerprint(target)
    if base_fingerprint is None:
      return None

    hasher.update(base_fingerprint)

    # NB: this series of updates must always cover the same fields that populate `_tuple`'s slots
    # to ensure proper invalidation.
    hasher.update(self._key)
    hasher.update(self._scope)
    hasher.update(self._main)
    if self._custom_rules:
      for rule in self._custom_rules:
        hasher.update(rule.render())

    return hasher.hexdigest()

  def _tuple(self):
    # NB: this tuple's slots - used for `==/hash()` - must be kept in agreement with the hashed
    # fields in `compute_fingerprint` to ensure proper invalidation.
    return self._key, self._scope, self._main, tuple(self._custom_rules or ())

  def __hash__(self):
    return hash((type(self),) + self._tuple())

  def __eq__(self, other):
    return type(self) == type(other) and self._tuple() == other._tuple()


class BootstrapJvmTools(IvyTaskMixin, JarTask):

  @classmethod
  def product_types(cls):
    return ['jvm_build_tools_classpath_callbacks']

  @classmethod
  def register_options(cls, register):
    super(BootstrapJvmTools, cls).register_options(register)
    cls.register_jvm_tool(register, 'jarjar')

  def __init__(self, *args, **kwargs):
    super(BootstrapJvmTools, self).__init__(*args, **kwargs)
    self._shader = None
    self._tool_cache_path = os.path.join(self.workdir, 'tool_cache')

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
      for scope, key, main, custom_rules in JvmToolTaskMixin.get_registered_tools():
        option = key.replace('-', '_')
        deplist = self.context.options.for_scope(scope)[option]
        callback_product_map[scope][key] = self.cached_bootstrap_classpath_callback(
            key, scope, deplist, main=main, custom_rules=custom_rules)
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
      except (KeyError, AddressLookupError):
        self.context.log.error("Failed to resolve target for tool: {tool}.\n"
                               "This target was obtained from option {option} in scope {scope}.\n"
                               "You probably need to add this target to your tools "
                               "BUILD file(s), usually located in the workspace root.\n"
                               "".format(tool=tool, scope=scope, option=key))
        raise TaskError()
      for target in targets:
        yield target

  def _bootstrap_classpath(self, key, targets):
    workunit_name = 'bootstrap-{}'.format(key)
    classpath, _ = self.ivy_resolve(targets, silent=True, workunit_name=workunit_name)
    return classpath

  def _bootstrap_tool_classpath(self, key, scope, tools):
    targets = list(self._resolve_tool_targets(tools, key, scope))
    return self._bootstrap_classpath(key, targets)

  @property
  def shader(self):
    if self._shader is None:
      jarjar_classpath = self.tool_classpath('jarjar')
      if len(jarjar_classpath) != 1:
        raise TaskError('Expected jarjar to resolve to one jar, instead found {}:\n\t{}'
                        .format(len(jarjar_classpath), '\n\t'.join(jarjar_classpath)))
      self._shader = Shader(jarjar_classpath.pop())
    return self._shader

  def _bootstrap_shaded_jvm_tool(self, key, scope, tools, main, custom_rules=None):
    shaded_jar = os.path.join(self._tool_cache_path,
                              'shaded_jars', scope, key, '{}.jar'.format(main))

    targets = list(self._resolve_tool_targets(tools, key, scope))
    fingerprint_strategy = ShadedToolFingerprintStrategy(key, scope, main,
                                                         custom_rules=custom_rules)
    with self.invalidated(targets,
                          # We're the only dependent in reality since we shade.
                          invalidate_dependents=False,
                          fingerprint_strategy=fingerprint_strategy) as invalidation_check:

      if not invalidation_check.invalid_vts and os.path.exists(shaded_jar):
        return [shaded_jar]

      # Ensure we have a single binary jar we can shade.
      binary_jar = os.path.join(self._tool_cache_path,
                                'binary_jars', scope, key, '{}.jar'.format(main))
      safe_mkdir_for(binary_jar)

      classpath = self._bootstrap_classpath(key, targets)
      if len(classpath) == 1:
        shutil.copy(classpath[0], binary_jar)
      else:
        with self.open_jar(binary_jar) as jar:
          for classpath_jar in classpath:
            jar.writejar(classpath_jar)
          jar.main(main)

      # Now shade the binary jar and return that single jar as the safe tool classpath.
      safe_mkdir_for(shaded_jar)
      with self.shader.binary_shader(shaded_jar, main, binary_jar,
                                     custom_rules=custom_rules) as shader:
        try:
          result = util.execute_runner(shader,
                                       workunit_factory=self.context.new_workunit,
                                       workunit_name='shade-{}'.format(key))
          if result != 0:
            raise TaskError("Shading of tool '{key}' with main class {main} for {scope} failed "
                            "with exit code {result}".format(key=key, main=main, scope=scope,
                                                             result=result))
        except Executor.Error as e:
          raise TaskError("Shading of tool '{key}' with main class {main} for {scope} failed "
                          "with: {exception}".format(key=key, main=main, scope=scope, exception=e))
      return [shaded_jar]

  def _bootstrap_jvm_tool(self, key, scope, tools, main, custom_rules=None):
    if main is None:
      return self._bootstrap_tool_classpath(key, scope, tools)
    else:
      return self._bootstrap_shaded_jvm_tool(key, scope, tools, main, custom_rules=custom_rules)

  def cached_bootstrap_classpath_callback(self, key, scope, tools, main=None, custom_rules=None):
    cache = {}
    cache_lock = threading.Lock()

    def bootstrap_classpath():
      with cache_lock:
        if 'classpath' not in cache:
          cache['classpath'] = self._bootstrap_jvm_tool(key, scope, tools,
                                                        main=main, custom_rules=custom_rules)
        return cache['classpath']
    return bootstrap_classpath
