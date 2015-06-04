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
from textwrap import dedent

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.tasks.ivy_task_mixin import IvyResolveFingerprintStrategy, IvyTaskMixin
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.base.address_lookup_error import AddressLookupError
from pants.base.cache_manager import VersionedTargetSet
from pants.base.exceptions import TaskError
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java import util
from pants.java.executor import Executor
from pants.java.jar.shader import Shader
from pants.util.dirutil import safe_mkdir_for


class ShadedToolFingerprintStrategy(IvyResolveFingerprintStrategy):
  def __init__(self, main, custom_rules=None):
    # The bootstrapper uses no custom confs in its resolves.
    super(ShadedToolFingerprintStrategy, self).__init__(confs=None)

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
    hasher.update(self._main)
    if self._custom_rules:
      for rule in self._custom_rules:
        hasher.update(rule.render())

    return hasher.hexdigest()

  def _tuple(self):
    # NB: this tuple's slots - used for `==/hash()` - must be kept in agreement with the hashed
    # fields in `compute_fingerprint` to ensure proper invalidation.
    return self._main, tuple(self._custom_rules or ())

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
    register('--jvm-options', action='append', metavar='<option>...',
             help='Run the tool shader with these extra jvm options.')
    cls.register_jvm_tool(register, 'jarjar')

  @classmethod
  def global_subsystems(cls):
    return super(BootstrapJvmTools, cls).global_subsystems() + (IvySubsystem, )

  def __init__(self, *args, **kwargs):
    super(BootstrapJvmTools, self).__init__(*args, **kwargs)
    self.setup_artifact_cache()
    self._shader = None
    self._tool_cache_path = os.path.join(self.workdir, 'tool_cache')

  def execute(self):
    context = self.context
    if JvmToolMixin.get_registered_tools():
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
      for scope, key, main, custom_rules in JvmToolMixin.get_registered_tools():
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
      except (KeyError, AddressLookupError) as e:
        msg = dedent("""
          Failed to resolve target for tool: {tool}. This target was obtained from
          option {option} in scope {scope}. You probably need to add this target to your tools
          BUILD file(s), usually located in BUILD.tools in the workspace root.
          Exception {etype}: {e}
        """.format(tool=tool, etype=type(e).__name__, e=e, scope=scope, option=key))
        self.context.log.error(msg)
        raise TaskError(msg)
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
      jarjar = self.tool_jar('jarjar')
      self._shader = Shader(jarjar)
    return self._shader

  def _bootstrap_shaded_jvm_tool(self, key, scope, tools, main, custom_rules=None):
    shaded_jar = os.path.join(self._tool_cache_path,
                              'shaded_jars', scope, key, '{}.jar'.format(main))

    targets = list(self._resolve_tool_targets(tools, key, scope))
    fingerprint_strategy = ShadedToolFingerprintStrategy(main, custom_rules=custom_rules)
    with self.invalidated(targets,
                          # We're the only dependent in reality since we shade.
                          invalidate_dependents=False,
                          fingerprint_strategy=fingerprint_strategy) as invalidation_check:
      shaded_tool_vts = self.tool_vts(invalidation_check)

      if not invalidation_check.invalid_vts:
        if not os.path.exists(shaded_jar) and self.artifact_cache_reads_enabled():
          self.context.log.debug('Cache entry for \'{}\' tool was found, '
                                 'but an actual jar doesn\'t exist. Extracting again...'.format(key))
          self.get_artifact_cache().use_cached_files(shaded_tool_vts.cache_key)
        if os.path.exists(shaded_jar):
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
      with self.shader.binary_shader(shaded_jar,
                                     main,
                                     binary_jar,
                                     custom_rules=custom_rules,
                                     jvm_options=self.get_options().jvm_options) as shader:
        try:
          result = util.execute_runner(shader,
                                       workunit_factory=self.context.new_workunit,
                                       workunit_name='shade-{}'.format(key))
          if result != 0:
            raise TaskError("Shading of tool '{key}' with main class {main} for {scope} failed "
                            "with exit code {result}, command run was:\n\t{cmd}"
                            .format(key=key, main=main, scope=scope, result=result, cmd=shader.cmd))
        except Executor.Error as e:
          raise TaskError("Shading of tool '{key}' with main class {main} for {scope} failed "
                          "with: {exception}".format(key=key, main=main, scope=scope, exception=e))

      if self.artifact_cache_writes_enabled():
        self.update_artifact_cache([(shaded_tool_vts, [shaded_jar])])

      return [shaded_jar]

  def check_artifact_cache_for(self, invalidation_check):
    tool_vts = self.tool_vts(invalidation_check)
    return [tool_vts]

  def tool_vts(self, invalidation_check):
    # The monolithic shaded tool jar is a single output dependent on the entire target set, and is
    # not divisible by target. So we can only cache it keyed by the entire target set.
    return VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

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
