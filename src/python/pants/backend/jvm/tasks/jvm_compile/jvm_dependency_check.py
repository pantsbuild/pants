# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
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
from pants.base.exceptions import TaskError
from pants.option.custom_types import list_option


class JvmDependencyCheck(Task):
  """Checks true dependencies of a JVM target and ensures they are consistent with BUILD files."""

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmDependencyCheck, cls).prepare(options, round_manager)
    round_manager.require_data('classes_by_target')
    round_manager.require_data('ivy_jar_products')
    round_manager.require_data('ivy_resolve_symlink_map')
    round_manager.require_data('actual_source_deps')

  @classmethod
  def register_options(cls, register):
    super(JvmDependencyCheck, cls).register_options(register)
    register('--missing-deps', choices=['off', 'warn', 'fatal'], default='warn',
             fingerprint=True,
             help='Check for missing dependencies in compiled code. Reports actual '
                  'dependencies A -> B where there is no transitive BUILD file dependency path '
                  'from A to B. If fatal, missing deps are treated as a build error.')

    register('--missing-direct-deps', choices=['off', 'warn', 'fatal'],
             default='off',
             fingerprint=True,
             help='Check for missing direct dependencies in compiled code. Reports actual '
                  'dependencies A -> B where there is no direct BUILD file dependency path from '
                  'A to B. This is a very strict check; In practice it is common to rely on '
                  'transitive, indirect dependencies, e.g., due to type inference or when the main '
                  'target in a BUILD file is modified to depend on other targets in the same BUILD '
                  'file, as an implementation detail. However it may still be useful to use this '
                  'on occasion. ')

    register('--missing-deps-whitelist', type=list_option, default=[],
             fingerprint=True,
             help="Don't report these targets even if they have missing deps.")

    register('--unnecessary-deps', choices=['off', 'warn', 'fatal'], default='off',
             fingerprint=True,
             help='Check for declared dependencies in compiled code that are not needed. '
                  'This is a very strict check. For example, generated code will often '
                  'legitimately have BUILD dependencies that are unused in practice.')

  def __init__(self, *args, **kwargs):
    super(JvmDependencyCheck, self).__init__(*args, **kwargs)

    # Set up dep checking if needed.
    def munge_flag(flag):
      flag_value = self.get_options().get(flag, None)
      return None if flag_value == 'off' else flag_value

    self._check_missing_deps = munge_flag('missing_deps')
    self._check_missing_direct_deps = munge_flag('missing_direct_deps')
    self._check_unnecessary_deps = munge_flag('unnecessary_deps')
    self._target_whitelist = self.get_options().missing_deps_whitelist

  def execute(self):
    for target in self.context.targets():
      actual_source_deps = self.context.products.get_data('actual_source_deps').get(target, None)
      if actual_source_deps is not None:
        self.check(target, actual_source_deps)

  def _compute_targets_by_file(self):
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
        for _, classes in target_products.abs_paths():
          for cls in classes:
            targets_by_file[cls].add(tgt)

    # Compute jar -> target.
    with self.context.new_workunit(name='map_jars'):
      with IvyTaskMixin.symlink_map_lock:
        all_symlinks_map = self.context.products.get_data('ivy_resolve_symlink_map').copy()
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

  def check(self, src_tgt, actual_deps):
    """Check for missing deps.

    See docstring for _compute_missing_deps for details.
    """
    if self._check_missing_deps or self._check_missing_direct_deps or self._check_unnecessary_deps:
      missing_file_deps, missing_tgt_deps, missing_direct_tgt_deps = \
        self._compute_missing_deps(src_tgt, actual_deps)

      buildroot = get_buildroot()

      def shorten(path):  # Make the output easier to read.
        if path.startswith(buildroot):
          return os.path.relpath(path, buildroot)
        return path

      def filter_whitelisted(missing_deps):
        # Removing any targets that exist in the whitelist from the list of dependency issues.
        return [(tgt_pair, evidence) for (tgt_pair, evidence) in missing_deps
                            if tgt_pair[0].address.reference() not in self._target_whitelist]

      missing_tgt_deps = filter_whitelisted(missing_tgt_deps)

      if self._check_missing_deps and (missing_file_deps or missing_tgt_deps):
        for (tgt_pair, evidence) in missing_tgt_deps:
          evidence_str = '\n'.join(['    {} uses {}'.format(shorten(e[0]), shorten(e[1]))
                                    for e in evidence])
          self.context.log.error(
              'Missing BUILD dependency {} -> {} because:\n{}'
              .format(tgt_pair[0].address.reference(), tgt_pair[1].address.reference(), evidence_str))
        for (src_tgt, dep) in missing_file_deps:
          self.context.log.error('Missing BUILD dependency {} -> {}'
                                  .format(src_tgt.address.reference(), shorten(dep)))
        if self._check_missing_deps == 'fatal':
          raise TaskError('Missing deps.')

      missing_direct_tgt_deps = filter_whitelisted(missing_direct_tgt_deps)

      if self._check_missing_direct_deps and missing_direct_tgt_deps:

        for (tgt_pair, evidence) in missing_direct_tgt_deps:
          evidence_str = '\n'.join(['    {} uses {}'.format(shorten(e[0]), shorten(e[1]))
                                    for e in evidence])
          self.context.log.warn('Missing direct BUILD dependency {} -> {} because:\n{}'
                                 .format(tgt_pair[0].address, tgt_pair[1].address, evidence_str))
        if self._check_missing_direct_deps == 'fatal':
          raise TaskError('Missing direct deps.')

      if self._check_unnecessary_deps:
        raise TaskError('Unnecessary dep warnings not implemented yet.')

  def _compute_missing_deps(self, src_tgt, actual_deps):
    """Computes deps that are used by the compiler but not specified in a BUILD file.

    These deps are bugs waiting to happen: the code may happen to compile because the dep was
    brought in some other way (e.g., by some other root target), but that is obviously fragile.

    Note that in practice we're OK with reliance on indirect deps that are only brought in
    transitively. E.g., in Scala type inference can bring in such a dep subtly. Fortunately these
    cases aren't as fragile as a completely missing dependency. It's still a good idea to have
    explicit direct deps where relevant, so we optionally warn about indirect deps, to make them
    easy to find and reason about.

    - actual_deps: a map src -> list of actual deps (source, class or jar file) as noted by the
      compiler.

    Returns a triple (missing_file_deps, missing_tgt_deps, missing_direct_tgt_deps) where:

    - missing_file_deps: a list of dep_files where src_tgt requires dep_file, and we're unable
      to map to a target (because its target isn't in the total set of targets in play,
      and we don't want to parse every BUILD file in the workspace just to find it).

    - missing_tgt_deps: a list of dep_tgt where src_tgt is missing a necessary transitive
                        dependency on dep_tgt.

    - missing_direct_tgt_deps: a list of dep_tgts where src_tgt is missing a direct dependency
                               on dep_tgt but has a transitive dep on it.

    All paths in the input and output are absolute.
    """
    def must_be_explicit_dep(dep):
      # We don't require explicit deps on the java runtime, so we shouldn't consider that
      # a missing dep.
      return not dep.startswith(self.context.java_home)

    def target_or_java_dep_in_targets(target, targets):
      # We want to check if the target is in the targets collection
      #
      # However, for the special case of scala_library that has a java_sources
      # reference we're ok if that exists in targets even if the scala_library does not.

      if target in targets:
        return True
      elif target.is_scala:
        return any(t in targets for t in target.java_sources)
      else:
        return False

    # TODO: If recomputing these every time becomes a performance issue, memoize for
    # already-seen targets and incrementally compute for new targets not seen in a previous
    # partition, in this or a previous chunk.
    targets_by_file = self._compute_targets_by_file()
    transitive_deps_by_target = self._compute_transitive_deps_by_target()

    # Find deps that are actual but not specified.
    with self.context.new_workunit(name='scan_deps'):
      missing_file_deps = OrderedSet()  # (src, src).
      missing_tgt_deps_map = defaultdict(list)  # (tgt, tgt) -> a list of (src, src) as evidence.
      missing_direct_tgt_deps_map = defaultdict(list)  # The same, but for direct deps.

      buildroot = get_buildroot()
      abs_srcs = [os.path.join(buildroot, src) for src in src_tgt.sources_relative_to_buildroot()]
      for src in abs_srcs:
        for actual_dep in filter(must_be_explicit_dep, actual_deps.get(src, [])):
          actual_dep_tgts = targets_by_file.get(actual_dep)
          # actual_dep_tgts is usually a singleton. If it's not, we only need one of these
          # to be in our declared deps to be OK.
          if actual_dep_tgts is None:
            missing_file_deps.add((src_tgt, actual_dep))
          elif not target_or_java_dep_in_targets(src_tgt, actual_dep_tgts):
            # Obviously intra-target deps are fine.
            canonical_actual_dep_tgt = next(iter(actual_dep_tgts))
            if actual_dep_tgts.isdisjoint(transitive_deps_by_target.get(src_tgt, [])):
              missing_tgt_deps_map[(src_tgt, canonical_actual_dep_tgt)].append((src, actual_dep))
            elif canonical_actual_dep_tgt not in src_tgt.dependencies:
              # The canonical dep is the only one a direct dependency makes sense on.
              missing_direct_tgt_deps_map[(src_tgt, canonical_actual_dep_tgt)].append(
                  (src, actual_dep))

    return (list(missing_file_deps),
            missing_tgt_deps_map.items(),
            missing_direct_tgt_deps_map.items())
