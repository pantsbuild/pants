# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.ivy_task_mixin import IvyTaskMixin
from pants.base.build_environment import get_buildroot
from pants.base.build_graph import sort_targets
from pants.util.memo import memoized_property


class JvmDependencyAnalyzer(Task):

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmDependencyAnalyzer, cls).prepare(options, round_manager)
    if not options.skip:
      round_manager.require_data('classes_by_target')
      round_manager.require_data('ivy_jar_products')
      round_manager.require_data('ivy_resolve_symlink_map')
      round_manager.require_data('actual_source_deps')

  @classmethod
  def register_options(cls, register):
    super(JvmDependencyAnalyzer, cls).register_options(register)
    register('--skip', default=False, action='store_true',
             fingerprint=True,
             help='Skip dependency analysis.')

  @memoized_property
  def targets_by_file(self):
    """Returns a map from abs path of source, class or jar file to an OrderedSet of targets.

    The value is usually a singleton, because a source or class file belongs to a single target.
    However a single jar may be provided (transitively or intransitively) by multiple JarLibrary
    targets. But if there is a JarLibrary target that depends on a jar directly, then that
    "canonical" target will be the first one in the list of targets.
    """
    targets_by_file = defaultdict(OrderedSet)

    # Multiple JarLibrary targets can provide the same (org, name).
    jarlibs_by_id = defaultdict(set)

    # Compute src -> target.
    with self.context.new_workunit(name='map_sources'):
      buildroot = get_buildroot()
      # Look at all targets in-play for this pants run. Does not include synthetic targets,
      for target in self.context.targets():
        if isinstance(target, JvmTarget):
          for src in target.sources_relative_to_buildroot():
            targets_by_file[os.path.join(buildroot, src)].add(target)
        elif isinstance(target, JarLibrary):
          for jardep in target.jar_dependencies:
            jarlibs_by_id[(jardep.org, jardep.name)].add(target)
        # TODO(Tejal Desai): pantsbuild/pants/65: Remove java_sources attribute for ScalaLibrary
        if isinstance(target, ScalaLibrary):
          for java_source in target.java_sources:
            for src in java_source.sources_relative_to_buildroot():
              targets_by_file[os.path.join(buildroot, src)].add(target)

    # Compute class -> target.
    with self.context.new_workunit(name='map_classes'):
      classes_by_target = self.context.products.get_data('classes_by_target')
      for tgt, target_products in classes_by_target.items():
        for classes_dir, classes in target_products.rel_paths():
          for cls in classes:
            targets_by_file[cls].add(tgt)
            targets_by_file[os.path.join(classes_dir, cls)].add(tgt)

    # Compute jar -> target.
    with self.context.new_workunit(name='map_jars'):
      with IvyTaskMixin.symlink_map_lock:
        m = self.context.products.get_data('ivy_resolve_symlink_map')
        all_symlinks_map = m.copy() if m is not None else {}
        # We make a copy, so it's safe to use outside the lock.

      def register_transitive_jars_for_ref(ivyinfo, ref):
        deps_by_ref_memo = {}

        def get_transitive_jars_by_ref(ref1):
          def create_collection(current_ref):
            return {ivyinfo.modules_by_ref[current_ref].artifact}
          return ivyinfo.traverse_dependency_graph(ref1, create_collection, memo=deps_by_ref_memo)

        target_key = (ref.org, ref.name)
        if target_key in jarlibs_by_id:
          # These targets provide all the jars in ref, and all the jars ref transitively depends on.
          jarlib_targets = jarlibs_by_id[target_key]

          for jar_path in get_transitive_jars_by_ref(ref):
            # Register that each jarlib_target provides jar (via all its symlinks).
            symlink = all_symlinks_map.get(os.path.realpath(jar_path), None)
            if symlink:
              for jarlib_target in jarlib_targets:
                targets_by_file[symlink].add(jarlib_target)

      ivy_products = self.context.products.get_data('ivy_jar_products')
      if ivy_products:
        for ivyinfos in ivy_products.values():
          for ivyinfo in ivyinfos:
            for ref in ivyinfo.modules_by_ref:
              register_transitive_jars_for_ref(ivyinfo, ref)

    return targets_by_file

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
