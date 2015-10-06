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
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.ivy_task_mixin import IvyResolveFingerprintStrategy, IvyTaskMixin
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.base.address import Address
from pants.base.address_lookup_error import AddressLookupError
from pants.base.exceptions import TaskError
from pants.build_graph.target import Target
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java import util
from pants.java.executor import Executor
from pants.util.dirutil import safe_mkdir_for
from pants.util.memo import memoized_property


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

    hasher.update('version=2')
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

  @classmethod
  def subsystem_dependencies(cls):
    return super(BootstrapJvmTools, cls).subsystem_dependencies() + (Shader.Factory,)

  @classmethod
  def global_subsystems(cls):
    return super(BootstrapJvmTools, cls).global_subsystems() + (IvySubsystem, )

  @classmethod
  def prepare(cls, options, round_manager):
    super(BootstrapJvmTools, cls).prepare(options, round_manager)
    Shader.Factory.prepare_tools(round_manager)

  class ToolResolveError(TaskError):
    """Indicates an error resolving a required JVM tool classpath."""

  @classmethod
  def _tool_resolve_error(cls, error, dep_spec, jvm_tool):
    msg = dedent("""
        Failed to resolve target for tool: {tool}. This target was obtained from
        option {option} in scope {scope}. You probably need to add this target to your tools
        BUILD file(s), usually located in BUILD.tools in the workspace root.
        Exception {etype}: {error}
      """.format(tool=dep_spec,
                 etype=type(error).__name__,
                 error=error,
                 scope=jvm_tool.scope,
                 option=jvm_tool.key))
    return cls.ToolResolveError(msg)

  @classmethod
  def _alternate_target_roots(cls, options, address_mapper, build_graph):
    processed = set()
    for jvm_tool in JvmToolMixin.get_registered_tools():
      dep_spec = jvm_tool.dep_spec(options)
      dep_address = Address.parse(dep_spec)
      # Some JVM tools are requested multiple times, we only need to handle them once.
      if dep_address not in processed:
        processed.add(dep_address)
        try:
          if build_graph.contains_address(dep_address) or address_mapper.resolve(dep_address):
            # The user has defined a tool classpath override - we let that stand.
            continue
        except AddressLookupError as e:
          if jvm_tool.classpath is None:
            raise cls._tool_resolve_error(e, dep_spec, jvm_tool)
          else:
            if not jvm_tool.is_default(options):
              # The user specified a target spec for this jvm tool that doesn't actually exist.
              # We want to error out here instead of just silently using the default option while
              # appearing to respect their config.
              raise cls.ToolResolveError(dedent("""
                  Failed to resolve target for tool: {tool}. This target was obtained from
                  option {option} in scope {scope}.

                  Make sure you didn't make a typo in the tool's address. You specified that the
                  tool should use the target found at "{tool}".

                  This target has a default classpath configured, so you can simply remove:
                    [{scope}]
                    {option}: {tool}
                  from pants.ini (or any other config file) to use the default tool.

                  The default classpath is: {default_classpath}

                  Note that tool target addresses in pants.ini should be specified *without* quotes.
                """).strip().format(tool=dep_spec,
                                    option=jvm_tool.key,
                                    scope=jvm_tool.scope,
                                    default_classpath=':'.join(map(str, jvm_tool.classpath or ()))))
            if jvm_tool.classpath:
              tool_classpath_target = JarLibrary(name=dep_address.target_name,
                                                 address=dep_address,
                                                 build_graph=build_graph,
                                                 jars=jvm_tool.classpath)
            else:
              # The tool classpath is empty by default, so we just inject a dummy target that
              # ivy resolves as the empty list classpath.  JarLibrary won't do since it requires
              # one or more jars, so we just pick a target type ivy has no resolve work to do for.
              tool_classpath_target = Target(name=dep_address.target_name,
                                             address=dep_address,
                                             build_graph=build_graph)
            build_graph.inject_target(tool_classpath_target)

    # We use the trick of not returning alternate roots, but instead just filling the dep_spec
    # holes with a JarLibrary built from a tool's default classpath JarDependency list if there is
    # no over-riding targets present. This means we do modify the build_graph, but we at least do
    # it at a time in the engine lifecycle cut out for handling that.
    return None

  def __init__(self, *args, **kwargs):
    super(BootstrapJvmTools, self).__init__(*args, **kwargs)
    self._tool_cache_path = os.path.join(self.workdir, 'tool_cache')

  def execute(self):
    registered_tools = JvmToolMixin.get_registered_tools()
    if registered_tools:
      # Map of scope -> (map of key -> callback).
      callback_product_map = self.context.products.get_data('jvm_build_tools_classpath_callbacks',
                                                            init_func=lambda: defaultdict(dict))
      # We leave a callback in the products map because we want these Ivy calls
      # to be done lazily (they might never actually get executed) and we want
      # to hit Task.invalidated (called in Task.ivy_resolve) on the instance of
      # BootstrapJvmTools rather than the instance of whatever class requires
      # the bootstrap tools.  It would be awkward and possibly incorrect to call
      # self.invalidated twice on a Task that does meaningful invalidation on its
      # targets. -pl
      for jvm_tool in registered_tools:
        dep_spec = jvm_tool.dep_spec(self.context.options)
        callback = self.cached_bootstrap_classpath_callback(dep_spec, jvm_tool)
        callback_product_map[jvm_tool.scope][jvm_tool.key] = callback

  def _resolve_tool_targets(self, dep_spec, jvm_tool):
    try:
      targets = list(self.context.resolve(dep_spec))
      if not targets:
        raise KeyError
      return targets
    except (KeyError, AddressLookupError) as e:
      raise self._tool_resolve_error(e, dep_spec, jvm_tool)

  def _bootstrap_classpath(self, jvm_tool, targets):
    workunit_name = 'bootstrap-{}'.format(jvm_tool.key)
    classpath, _, _ = self.ivy_resolve(targets, silent=True, workunit_name=workunit_name)
    return classpath

  @memoized_property
  def shader(self):
    return Shader.Factory.create(self.context)

  def _bootstrap_shaded_jvm_tool(self, jvm_tool, targets):
    fingerprint_strategy = ShadedToolFingerprintStrategy(jvm_tool.main,
                                                         custom_rules=jvm_tool.custom_rules)

    with self.invalidated(targets,
                          # We're the only dependent in reality since we shade.
                          invalidate_dependents=False,
                          fingerprint_strategy=fingerprint_strategy) as invalidation_check:

      # If there are no vts, then there are no resolvable targets, so we exit early with an empty
      # classpath.  This supports the optional tool classpath case.
      if not invalidation_check.all_vts:
        return []

      tool_vts = self.tool_vts(invalidation_check)
      jar_name = '{main}-{hash}.jar'.format(main=jvm_tool.main, hash=tool_vts.cache_key.hash)
      shaded_jar = os.path.join(self._tool_cache_path, 'shaded_jars', jar_name)

      if not invalidation_check.invalid_vts and os.path.exists(shaded_jar):
        return [shaded_jar]

      # Ensure we have a single binary jar we can shade.
      binary_jar = os.path.join(self._tool_cache_path, 'binary_jars', jar_name)
      safe_mkdir_for(binary_jar)

      classpath = self._bootstrap_classpath(jvm_tool, targets)
      if len(classpath) == 1:
        shutil.copy(classpath[0], binary_jar)
      else:
        with self.open_jar(binary_jar) as jar:
          for classpath_jar in classpath:
            jar.writejar(classpath_jar)
          jar.main(jvm_tool.main)

      # Now shade the binary jar and return that single jar as the safe tool classpath.
      safe_mkdir_for(shaded_jar)
      with self.shader.binary_shader(shaded_jar,
                                     jvm_tool.main,
                                     binary_jar,
                                     custom_rules=jvm_tool.custom_rules,
                                     jvm_options=self.get_options().jvm_options) as shader:
        try:
          result = util.execute_runner(shader,
                                       workunit_factory=self.context.new_workunit,
                                       workunit_name='shade-{}'.format(jvm_tool.key))
          if result != 0:
            raise TaskError("Shading of tool '{key}' with main class {main} for {scope} failed "
                            "with exit code {result}, command run was:\n\t{cmd}"
                            .format(key=jvm_tool.key,
                                    main=jvm_tool.main,
                                    scope=jvm_tool.scope,
                                    result=result,
                                    cmd=shader.cmd))
        except Executor.Error as e:
          raise TaskError("Shading of tool '{key}' with main class {main} for {scope} failed "
                          "with: {exception}".format(key=jvm_tool.key,
                                                     main=jvm_tool.main,
                                                     scope=jvm_tool.scope,
                                                     exception=e))

      if self.artifact_cache_writes_enabled():
        self.update_artifact_cache([(tool_vts, [shaded_jar])])

      return [shaded_jar]

  def check_artifact_cache_for(self, invalidation_check):
    tool_vts = self.tool_vts(invalidation_check)
    return [tool_vts]

  def tool_vts(self, invalidation_check):
    # The monolithic shaded tool jar is a single output dependent on the entire target set, and is
    # not divisible by target. So we can only cache it keyed by the entire target set.
    return VersionedTargetSet.from_versioned_targets(invalidation_check.all_vts)

  def _bootstrap_jvm_tool(self, dep_spec, jvm_tool):
    targets = self._resolve_tool_targets(dep_spec, jvm_tool)
    if jvm_tool.main is None:
      return self._bootstrap_classpath(jvm_tool, targets)
    else:
      return self._bootstrap_shaded_jvm_tool(jvm_tool, targets)

  def cached_bootstrap_classpath_callback(self, dep_spec, jvm_tool):
    cache = {}
    cache_lock = threading.Lock()

    def bootstrap_classpath():
      with cache_lock:
        if 'classpath' not in cache:
          cache['classpath'] = self._bootstrap_jvm_tool(dep_spec, jvm_tool)
        return cache['classpath']
    return bootstrap_classpath
