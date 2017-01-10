# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.build_graph.aliased_target import AliasTarget
from pants.build_graph.build_graph import sort_targets
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.build_graph.target_scopes import Scopes
from pants.java.distribution.distribution import DistributionLocator
from pants.util.memo import memoized_method, memoized_property


class JvmDependencyAnalyzer(object):
  """Helper class for tasks which need to analyze source dependencies.

  Primary purpose is to provide a classfile --> target mapping, which subclasses can use in
  determining which targets correspond to the actual source dependencies of any given target.
  """

  def __init__(self, buildroot, runtime_classpath, product_deps_by_src):
    self.buildroot = buildroot
    self.runtime_classpath = runtime_classpath
    self.product_deps_by_src = product_deps_by_src

  @memoized_method
  def files_for_target(self, target):
    """Yields a sequence of abs path of source, class or jar files provided by the target.

    The runtime classpath for a target must already have been finalized for a target in order
    to compute its provided files.
    """
    def gen():
      # Compute src -> target.
      if isinstance(target, JvmTarget):
        for src in target.sources_relative_to_buildroot():
          yield os.path.join(self.buildroot, src)
      # TODO(Tejal Desai): pantsbuild/pants/65: Remove java_sources attribute for ScalaLibrary
      if isinstance(target, ScalaLibrary):
        for java_source in target.java_sources:
          for src in java_source.sources_relative_to_buildroot():
            yield os.path.join(self.buildroot, src)

      # Compute classfile -> target and jar -> target.
      files = ClasspathUtil.classpath_contents((target,), self.runtime_classpath)
      # And jars; for binary deps, zinc doesn't emit precise deps (yet).
      cp_entries = ClasspathUtil.classpath((target,), self.runtime_classpath)
      jars = [cpe for cpe in cp_entries if ClasspathUtil.is_jar(cpe)]
      for coll in [files, jars]:
        for f in coll:
          yield f
    return set(gen())

  def targets_by_file(self, targets):
    """Returns a map from abs path of source, class or jar file to an OrderedSet of targets.

    The value is usually a singleton, because a source or class file belongs to a single target.
    However a single jar may be provided (transitively or intransitively) by multiple JarLibrary
    targets. But if there is a JarLibrary target that depends on a jar directly, then that
    "canonical" target will be the first one in the list of targets.
    """
    targets_by_file = defaultdict(OrderedSet)

    for target in targets:
      for f in self.files_for_target(target):
        targets_by_file[f].add(target)

    return targets_by_file

  def targets_for_class(self, target, classname):
    """Search which targets from `target`'s transitive dependencies contain `classname`."""
    targets_with_class = set()
    for target in target.closure():
      if classname in self._target_classes(target):
        targets_with_class.add(target)

    return targets_with_class

  @memoized_method
  def _target_classes(self, target):
    """Set of target's provided classes.

    Call at the target level is to memoize efficiently.
    """
    target_classes = set()
    contents = ClasspathUtil.classpath_contents((target,), self.runtime_classpath)
    for f in contents:
      classname = ClasspathUtil.classname_for_rel_classfile(f)
      if classname:
        target_classes.add(classname)
    return target_classes

  def _jar_classfiles(self, jar_file):
    """Returns an iterator over the classfiles inside jar_file."""
    for cls in ClasspathUtil.classpath_entries_contents([jar_file]):
      if cls.endswith(b'.class'):
        yield cls

  def count_products(self, target):
    contents = ClasspathUtil.classpath_contents((target,), self.runtime_classpath)
    # Generators don't implement len.
    return sum(1 for _ in contents)

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

  def compute_transitive_deps_by_target(self, targets):
    """Map from target to all the targets it depends on, transitively."""
    # Sort from least to most dependent.
    sorted_targets = reversed(sort_targets(targets))
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

  def resolve_aliases(self, target, scope=None):
    """Resolve aliases in the direct dependencies of the target.

    :param target: The direct dependencies of this target are included.
    :param scope: When specified, only deps with this scope are included. This is more
      than a filter, because it prunes the subgraphs represented by aliases with
      un-matched scopes.
    :returns: An iterator of (resolved_dependency, resolved_from) tuples.
      `resolved_from` is the top level target alias that depends on `resolved_dependency`,
      and `None` if `resolved_dependency` is not a dependency of a target alias.
    """
    for declared in target.dependencies:
      if scope is not None and declared.scope != scope:
        # Only `DEFAULT` scoped deps are eligible for the unused dep check.
        continue
      elif type(declared) in (AliasTarget, Target):
        # Is an alias. Recurse to expand.
        for r, _ in self.resolve_aliases(declared, scope=scope):
          yield r, declared
      else:
        yield declared, None

  def compute_unused_deps(self, target):
    """Computes unused deps for the given Target.

    :returns: A set of directly declared but unused targets, and a set of suggested replacements.
    """

    # Flatten the product deps of this target.
    product_deps = set()
    for dep_entries in self.product_deps_by_src.get(target, {}).values():
      product_deps.update(dep_entries)

    # Determine which of the DEFAULT deps in the declared set of this target were used.
    used = set()
    unused = set()
    for dep, _ in self.resolve_aliases(target, scope=Scopes.DEFAULT):
      if dep in used or dep in unused:
        continue
      # TODO: What's a better way to accomplish this check? Filtering by `has_sources` would
      # incorrectly skip "empty" `*_library` targets, which could then be used as a loophole.
      if isinstance(dep, (Resources, UnpackedJars)):
        continue
      # If any of the target's jars or classfiles were used, consider it used.
      if product_deps.isdisjoint(self.files_for_target(dep)):
        unused.add(dep)
      else:
        used.add(dep)

    # If there were no unused deps, break.
    if not unused:
      return {}

    # For any deps that were used, count their derived-from targets used as well.
    # TODO: Refactor to do some of this above once tests are in place.
    for dep in list(used):
      for derived_from in dep.derived_from_chain:
        if derived_from in unused:
          unused.remove(derived_from)
          used.add(derived_from)

    # Prune derived targets that would be in the set twice.
    for dep in list(unused):
      if set(dep.derived_from_chain) & unused:
        unused.remove(dep)

    if not unused:
      return {}

    # For any deps that were not used, determine whether their transitive deps were used, and
    # recommend those as replacements.
    replacements = {}
    for dep in unused:
      replacements[dep] = set()
      for t in dep.closure():
        if t in used or t in unused:
          continue
        if not product_deps.isdisjoint(self.files_for_target(t)):
          replacements[dep].add(t.concrete_derived_from)

    return replacements
