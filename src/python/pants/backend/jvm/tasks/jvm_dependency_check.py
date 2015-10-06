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
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.build_graph import sort_targets
from pants.java.distribution.distribution import DistributionLocator
from pants.option.custom_types import list_option


class JvmDependencyCheck(JvmDependencyAnalyzer):
  """Checks true dependencies of a JVM target and ensures that they are consistent with BUILD files."""

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

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    if self.get_options().skip:
      return
    with self.invalidated(self.context.targets(),
                          invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.invalid_vts:
        product_deps_by_src = self.context.products.get_data('product_deps_by_src').get(vt.target)
        if product_deps_by_src is not None:
          self.check(vt.target, product_deps_by_src)

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
        log_fn = (self.context.log.error if self._check_missing_deps == 'fatal'
                  else self.context.log.warn)
        for (tgt_pair, evidence) in missing_tgt_deps:
          evidence_str = '\n'.join(['    {} uses {}'.format(shorten(e[0]), shorten(e[1]))
                                    for e in evidence])
          log_fn('Missing BUILD dependency {} -> {} because:\n{}'
                 .format(tgt_pair[0].address.reference(), tgt_pair[1].address.reference(),
                         evidence_str))
        for (src_tgt, dep) in missing_file_deps:
          log_fn('Missing BUILD dependency {} -> {}'
                 .format(src_tgt.address.reference(), shorten(dep)))
        if self._check_missing_deps == 'fatal':
          raise TaskError('Missing deps.')

      missing_direct_tgt_deps = filter_whitelisted(missing_direct_tgt_deps)

      if self._check_missing_direct_deps and missing_direct_tgt_deps:
        log_fn = (self.context.log.error if self._check_missing_direct_deps == 'fatal'
                  else self.context.log.warn)
        for (tgt_pair, evidence) in missing_direct_tgt_deps:
          evidence_str = '\n'.join(['    {} uses {}'.format(shorten(e[0]), shorten(e[1]))
                                    for e in evidence])
          log_fn('Missing direct BUILD dependency {} -> {} because:\n{}'
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
      return (dep not in self.bootstrap_jar_classfiles
              and not dep.startswith(DistributionLocator.cached().real_home))

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
    transitive_deps_by_target = self._compute_transitive_deps_by_target()

    # Find deps that are actual but not specified.
    missing_file_deps = OrderedSet()  # (src, src).
    missing_tgt_deps_map = defaultdict(list)  # (tgt, tgt) -> a list of (src, src) as evidence.
    missing_direct_tgt_deps_map = defaultdict(list)  # The same, but for direct deps.

    buildroot = get_buildroot()
    abs_srcs = [os.path.join(buildroot, src) for src in src_tgt.sources_relative_to_buildroot()]
    for src in abs_srcs:
      for actual_dep in filter(must_be_explicit_dep, actual_deps.get(src, [])):
        actual_dep_tgts = self.targets_by_file.get(actual_dep)
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
