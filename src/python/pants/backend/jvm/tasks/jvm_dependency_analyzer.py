# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractmethod
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.base.build_environment import get_buildroot
from pants.build_graph.build_graph import sort_targets
from pants.java.distribution.distribution import DistributionLocator
from pants.util.contextutil import open_zip
from pants.util.memo import memoized_property


class JvmDependencyAnalyzer(Task):
  """Abstract class for tasks which need to analyze actual source dependencies.

  Primary purpose is to provide a classfile --> target mapping, which subclasses can use in
  determining which targets correspond to the actual source dependencies of any given target.
  """

  @classmethod
  @abstractmethod
  def skip(cls, options):
    """Return true if the task should be entirely skipped, and thus have no product requirements."""
    pass

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmDependencyAnalyzer, cls).prepare(options, round_manager)
    if not cls.skip(options):
      round_manager.require_data('runtime_classpath')
      round_manager.require_data('product_deps_by_src')

  @memoized_property
  def targets_by_file(self):
    """Returns a map from abs path of source, class or jar file to an OrderedSet of targets.

    The value is usually a singleton, because a source or class file belongs to a single target.
    However a single jar may be provided (transitively or intransitively) by multiple JarLibrary
    targets. But if there is a JarLibrary target that depends on a jar directly, then that
    "canonical" target will be the first one in the list of targets.
    """
    targets_by_file = defaultdict(OrderedSet)
    runtime_classpath = self.context.products.get_data('runtime_classpath')

    # Compute src -> target.
    self.context.log.debug('Mapping sources...')
    buildroot = get_buildroot()
    # Look at all targets in-play for this pants run. Does not include synthetic targets,
    for target in self.context.targets():
      if isinstance(target, JvmTarget):
        for src in target.sources_relative_to_buildroot():
          targets_by_file[os.path.join(buildroot, src)].add(target)
      # TODO(Tejal Desai): pantsbuild/pants/65: Remove java_sources attribute for ScalaLibrary
      if isinstance(target, ScalaLibrary):
        for java_source in target.java_sources:
          for src in java_source.sources_relative_to_buildroot():
            targets_by_file[os.path.join(buildroot, src)].add(target)

    # Compute classfile -> target and jar -> target.
    self.context.log.debug('Mapping classpath...')
    for target in self.context.targets():
      # Classpath content.
      files = ClasspathUtil.classpath_contents((target,), runtime_classpath)
      # And jars; for binary deps, zinc doesn't emit precise deps (yet).
      cp_entries = ClasspathUtil.classpath((target,), runtime_classpath)
      jars = [cpe for cpe in cp_entries if ClasspathUtil.is_jar(cpe)]
      for coll in [files, jars]:
        for f in coll:
          targets_by_file[f].add(target)

    return targets_by_file

  def _jar_classfiles(self, jar_file):
    """Returns an iterator over the classfiles inside jar_file."""
    with open_zip(jar_file, 'r') as jar:
      for cls in jar.namelist():
        if cls.endswith(b'.class'):
          yield cls

  @memoized_property
  def bootstrap_jar_classfiles(self):
    """Returns a set of classfiles from the JVM bootstrap jars."""
    bootstrap_jar_classfiles = set()
    for jar_file in self._find_all_bootstrap_jars():
      for cls in self._jar_classfiles(jar_file):
        bootstrap_jar_classfiles.add(cls)
    return bootstrap_jar_classfiles

  def _find_all_bootstrap_jars(self):
    def get_path(key):
      return DistributionLocator.cached().system_properties.get(key, '').split(':')

    def find_jars_in_dirs(dirs):
      ret = []
      for d in dirs:
        if os.path.isdir(d):
          ret.extend(filter(lambda s: s.endswith('.jar'), os.listdir(d)))
      return ret

    # Note: assumes HotSpot, or some JVM that supports sun.boot.class.path.
    # TODO: Support other JVMs? Not clear if there's a standard way to do so.
    # May include loose classes dirs.
    boot_classpath = get_path('sun.boot.class.path')

    # Note that per the specs, overrides and extensions must be in jars.
    # Loose class files will not be found by the JVM.
    override_jars = find_jars_in_dirs(get_path('java.endorsed.dirs'))
    extension_jars = find_jars_in_dirs(get_path('java.ext.dirs'))

    # Note that this order matters: it reflects the classloading order.
    bootstrap_jars = filter(os.path.isfile, override_jars + boot_classpath + extension_jars)
    return bootstrap_jars  # Technically, may include loose class dirs from boot_classpath.

  def _compute_transitive_deps_by_target(self):
    """Map from target to all the targets it depends on, transitively."""
    # Sort from least to most dependent.
    sorted_targets = reversed(sort_targets(self.context.targets()))
    transitive_deps_by_target = defaultdict(set)
    # Iterate in dep order, to accumulate the transitive deps for each target.
    for target in sorted_targets:
      transitive_deps = set()
      for dep in target.dependencies:
        transitive_deps.update(transitive_deps_by_target.get(dep, []))
        transitive_deps.add(dep)

      # Need to handle the case where a java_sources target has dependencies.
      # In particular if it depends back on the original target.
      if hasattr(target, 'java_sources'):
        for java_source_target in target.java_sources:
          for transitive_dep in java_source_target.dependencies:
            transitive_deps_by_target[java_source_target].add(transitive_dep)

      transitive_deps_by_target[target] = transitive_deps
    return transitive_deps_by_target
