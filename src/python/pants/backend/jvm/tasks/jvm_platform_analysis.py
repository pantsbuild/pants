# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from collections import defaultdict, namedtuple
from hashlib import sha1

from colors import red

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.core.tasks.task import Task
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TaskError
from pants.base.fingerprint_strategy import FingerprintStrategy
from pants.build_graph.build_graph import CycleException, sort_targets
from pants.util.memo import memoized_property


class JvmPlatformAnalysisMixin(object):
  """Mixin which provides common helper methods to JvmPlatformValidate and JvmPlatformExplain."""

  @classmethod
  def _is_jvm_target(cls, target):
    return isinstance(target, JvmTarget)

  @classmethod
  def jvm_version(cls, target):
    return target.platform.target_level

  @memoized_property
  def jvm_targets(self):
    return frozenset(self.context.targets(self._is_jvm_target))

  def _unfiltered_jvm_dependency_map(self, fully_transitive=False):
    """Jvm dependency map without filtering out non-JvmTarget keys, exposed for testing.

    Unfiltered because the keys in the resulting map include non-JvmTargets.

    See the explanation in the jvm_dependency_map() docs for what this method produces.

    :param fully_transitive: if true, the elements of the map will be the full set of transitive
      JvmTarget dependencies, not just the "direct" ones. (see jvm_dependency_map for the definition
      of "direct")
    :return: map of target -> set of JvmTarget "direct" dependencies.
    """
    targets = self.jvm_targets
    jvm_deps = defaultdict(set)

    def accumulate_jvm_deps(target):
      for dep in target.dependencies:
        if self._is_jvm_target(dep):
          jvm_deps[target].add(dep)
          if not fully_transitive:
            continue
        # If 'dep' isn't in jvm_deps, that means that it isn't in the `targets` list at all
        # (since this is a post-order traversal). If it's not in the targets list at all,
        # that means it cannot have any JvmTargets as transitive dependencies. In which case
        # we don't care about it, so it's fine that the line below is a no-op.
        #
        # Otherwise, we add in any transitive dependencies that were previously collected.
        jvm_deps[target].update(jvm_deps[dep])

    # Vanilla DFS runs in O(|V|+|E|), and the code inside the loop in accumulate_jvm_deps ends up
    # being run once for each in the graph over the course of the entire search, which means that
    # the total asymptotic runtime complexity is O(|V|+2|E|), which is still O(|V|+|E|).
    self.context.build_graph.walk_transitive_dependency_graph(
      addresses=[t.address for t in targets],
      work=accumulate_jvm_deps,
      postorder=True
    )

    return jvm_deps

  @memoized_property
  def jvm_dependency_map(self):
    """A map of each JvmTarget in the context to the set of JvmTargets it depends on "directly".

    "Directly" is in quotes here because it isn't quite the same as its normal use, which would be
    filter(self._is_jvm_target, target.dependencies).

    For this method, we define the set of dependencies which `target` depends on "directly" as:

    { dep | dep is a JvmTarget and exists a directed path p from target to dep such that |p| = 1 }

    Where |p| is computed as the weighted sum of all edges in the path, where edges to a JvmTarget
    have weight 1, and all other edges have weight 0.

    In other words, a JvmTarget 'A' "directly" depends on a JvmTarget 'B' iff there exists a path in
    the directed dependency graph from 'A' to 'B' such that there are no internal vertices in the
    path that are JvmTargets.

    This set is a (not necessarily proper) subset of the set of all JvmTargets that the target
    transitively depends on. The algorithms using this map *would* operate correctly on the full
    transitive superset, but it is more efficient to use this subset.

    The intuition for why we can get away with using this subset: Consider targets A, b, C, D,
    such that A depends on b, which depends on C, which depends on D. Say A,C,D are JvmTargets.

    If A is on java 6 and C is on java 7, we obviously have a problem, and this will be correctly
    identified when verifying the jvm dependencies of A, because the path A->b->C has length 1.

    If instead, A is on java 6, and C is on java 6, but D is on java 7, we still have a problem.
    It will not be detected when processing A, because A->b->C->D has length 2. But when we process
    C, it will be picked up, because C->D has length 1.

    Unfortunately, we can't do something as simple as just using actual direct dependencies, because
    it's perfectly legal for a java 6 A to depend on b (which is a non-JvmTarget), and legal for
    b to depend on a java 7 C, so the transitive information is needed to correctly identify the
    problem.

    :return: the dict mapping JvmTarget -> set of JvmTargets.
    """
    jvm_deps = self._unfiltered_jvm_dependency_map()
    return {target: deps for target, deps in jvm_deps.items()
            if deps and self._is_jvm_target(target)}


class JvmPlatformValidate(JvmPlatformAnalysisMixin, Task):
  """Validation step that runs well in advance of jvm compile.

  Ensures that no jvm targets depend on other targets which use a newer platform.
  """

  class IllegalJavaTargetLevelDependency(TaskError):
    """A jvm target depends on another jvm target with a newer java target level.

    E.g., a java_library targeted for Java 6 depends on a java_library targeted for java 7.
    """

  class PlatformFingerprintStrategy(FingerprintStrategy):
    """Fingerprint strategy which only cares a target's platform and dependency ids."""

    def compute_fingerprint(self, target):
      hasher = sha1()
      if hasattr(target, 'platform'):
        hasher.update(str(tuple(target.platform)))
      return hasher.hexdigest()

    def __eq__(self, other):
      return type(self) == type(other)

    def __hash__(self):
      return hash(type(self).__name__)

  @classmethod
  def product_types(cls):
    # NB(gmalmquist): These are fake products inserted to make sure validation is run very early.
    # There's no point in doing lots of code-gen and compile work if it's doomed to fail.  The
    # 'java' product type indicates this task does codegen for java.
    # TODO(John Sirois): plug this into a pre-products validation phase when one becomes available
    # instead of using fake products.
    return ['java']

  @classmethod
  def register_options(cls, register):
    super(JvmPlatformValidate, cls).register_options(register)
    register('--check', default='fatal', choices=['off', 'warn', 'fatal'], fingerprint=True,
             help='Check to make sure no jvm targets target an earlier jdk than their dependencies')
    register('--children-before-parents', default=False, action='store_true',
             fingerprint=True,
             help='Organize output in the form target -> dependencies, rather than '
                  'target -> dependees.')

  def __init__(self, *args, **kwargs):
    super(JvmPlatformValidate, self).__init__(*args, **kwargs)
    self.check = self.get_options().check
    self.parents_before_children = not self.get_options().children_before_parents

  def validate_platform_dependencies(self):
    """Check all jvm targets in the context, throwing an error or warning if there are bad targets.

    If there are errors, this method fails slow rather than fails fast -- that is, it continues
    checking the rest of the targets before spitting error messages. This is useful, because it's
    nice to have a comprehensive list of all errors rather than just the first one we happened to
    hit.
    """
    conflicts = []

    def is_conflicting(target, dependency):
      return self.jvm_version(dependency) > self.jvm_version(target)

    try:
      sort_targets(self.jvm_targets)
    except CycleException:
      self.context.log.warn('Cannot validate dependencies when cycles exist in the build graph.')
      return

    try:
      with self.invalidated(self.jvm_targets,
                            fingerprint_strategy=self.PlatformFingerprintStrategy(),
                            invalidate_dependents=True) as vts:
        dependency_map = self.jvm_dependency_map
        for vts_target in vts.invalid_vts:
          for target in vts_target.targets:
            if target in dependency_map:
              deps = dependency_map[target]
              invalid_dependencies = [dep for dep in deps if is_conflicting(target, dep)]
              if invalid_dependencies:
                conflicts.append((target, invalid_dependencies))
        if conflicts:
          # NB(gmalmquist): It's important to unconditionally raise an exception, then decide later
          # whether to continue raising it or just print a warning, to make sure the targets aren't
          # marked as valid if there are invalid platform dependencies.
          error_message = self._create_full_error_message(conflicts)
          raise self.IllegalJavaTargetLevelDependency(error_message)
    except self.IllegalJavaTargetLevelDependency as e:
      if self.check == 'fatal':
        raise e
      else:
        assert self.check == 'warn'
        self.context.log.warn(error_message)
        return error_message

  def _create_individual_error_message(self, target, invalid_dependencies):
    return '\n  {target} targeting "{platform_name}"\n  {relationship}: {dependencies}'.format(
      target=target.address.spec,
      platform_name=target.platform.name,
      dependencies=''.join('\n    {} targeting "{}"'.format(d.address.spec, d.platform.name)
                           for d in sorted(invalid_dependencies)),
      relationship='is depended on by' if self.parents_before_children else 'depends on',
    )

  def _create_full_error_message(self, invalids):
    if self.parents_before_children:
      dependency_to_dependees = defaultdict(set)
      for target, deps in invalids:
        for dep in deps:
          dependency_to_dependees[dep].add(target)
      invalids = dependency_to_dependees.items()

    invalids = sorted(invalids)
    individual_errors = '\n'.join(self._create_individual_error_message(target, deps)
                                  for target, deps in invalids)
    return ('Dependencies cannot have a higher java target level than dependees!\n{errors}\n\n'
            'Consider running ./pants jvm-platform-explain with the same targets for more details.'
            .format(errors=individual_errors))

  def execute(self):
    if self.check != 'off':
      # Return value is just for unit testing.
      return self.validate_platform_dependencies()


class JvmPlatformExplain(JvmPlatformAnalysisMixin, ConsoleTask):
  """Console task which provides helpful analysis about jvm platform dependencies.

  This can be very useful when debugging inter-dependencies in large sets of targets with a variety
  of jvm platforms.

  By default, this calculates the minimum and maximum possible -target level of each JvmTarget
  specified, printing the range for each one on the console. This is determined by a target's
  dependencies and dependees: a target cannot have a higher -target level than its dependees, and
  it cannot have a lower -target level than any of its dependencies.

  Additional flags fine-tune this output, including printing more detailed analysis of which
  dependencies/dependees are limiting a target, or filtering the output to only targets you care
  about.

  Besides this functionality, --upgradeable and --downgradeable can print lists of targets which
  can (again, based on the limits of their dependencies and dependees) afford to be upgraded or
  downgraded to a different version.
  """

  Ranges = namedtuple('ranges', ['min_allowed_version', 'max_allowed_version',
                                 'target_dependencies', 'target_dependees'])

  @classmethod
  def register_options(cls, register):
    super(JvmPlatformExplain, cls).register_options(register)
    register('--ranges', action='store_true', default=True,
             help='For each target, list the minimum and maximum possible jvm target level, based '
                  'on its dependencies and dependees, respectively.')
    register('--detailed', action='store_true', default=False,
             help='Always list the dependencies and dependees that contributed to the assessment of '
                  'legal jvm target levels (rather than only on failure).')
    register('--only-broken', action='store_true', default=False,
             help='Only print jvm target level ranges for targets with currently invalid ranges.')
    register('--upgradeable', action='store_true', default=False,
             help='Print a list of targets which can be upgraded to a higher version than they '
                  'currently are.')
    register('--downgradeable', action='store_true', default=False,
             help='Print a list of targets which can be downgraded to a lower version than they '
                  'currently are.')
    register('--filter',
             help='Limit jvm platform possibility explanation to targets whose specs match this '
                  'regex pattern.')
    register('--transitive', action='store_true', default=False,
             help='List transitive dependencies in analysis output.')

  def __init__(self, *args, **kwargs):
    super(JvmPlatformExplain, self).__init__(*args, **kwargs)
    self.explain_regex = (re.compile(self.get_options().filter) if self.get_options().filter
                          else None)
    self.detailed = self.get_options().detailed
    self.only_broken = self.get_options().only_broken
    self.transitive = self.get_options().transitive

  def _format_error(self, text):
    if self.get_options().colors:
      return red(text)
    return text

  def _is_relevant(self, target):
    return not self.explain_regex or self.explain_regex.match(target.address.spec)

  @memoized_property
  def dependency_map(self):
    if not self.transitive:
      return self.jvm_dependency_map
    full_map = self._unfiltered_jvm_dependency_map(fully_transitive=True)
    return {target: deps for target, deps in full_map.items()
            if self._is_jvm_target(target) and deps}

  @memoized_property
  def _ranges(self):
    target_dependencies = defaultdict(set)
    target_dependencies.update(self.dependency_map)

    target_dependees = defaultdict(set)
    for target, deps in target_dependencies.items():
      for dependency in deps:
        target_dependees[dependency].add(target)

    max_allowed_version = {}
    min_allowed_version = {}

    def get_versions(targets):
      return map(self.jvm_version, targets)

    for target in self.jvm_targets:
      if target_dependencies[target]:
        # A target's version must at least as high as its dependencies.
        min_allowed_version[target] = max(get_versions(target_dependencies[target]))
      if target_dependees[target]:
        # A target can't have a higher version than any of its dependees.
        max_allowed_version[target] = min(get_versions(target_dependees[target]))

    return self.Ranges(min_allowed_version, max_allowed_version, target_dependencies,
                       target_dependees)

  def possible_version_evaluation(self):
    """Evaluate the possible range of versions for each target, yielding the output analysis."""
    ranges = self._ranges
    yield 'Allowable JVM platform ranges (* = anything):'
    for target in sorted(filter(self._is_relevant, self.jvm_targets)):
      min_version = ranges.min_allowed_version.get(target)
      max_version = ranges.max_allowed_version.get(target)
      current_valid = True
      if min_version and self.jvm_version(target) < min_version:
        current_valid = False
      if max_version and self.jvm_version(target) > max_version:
        current_valid = False
      current_text = str(self.jvm_version(target))
      if not current_valid:
        current_text = self._format_error(current_text)
      elif self.only_broken:
        continue

      if min_version and max_version:
        range_text = '{} to {}'.format(min_version, max_version)
        if min_version > max_version:
          range_text = self._format_error(range_text)
      elif min_version:
        range_text = '{}+'.format(min_version)
      elif max_version:
        range_text = '<={}'.format(max_version)
      else:
        range_text = '*'
      yield '{address}: {range}  (is {current})'.format(address=target.address.spec,
                                                        range=range_text,
                                                        current=current_text,)
      if self.detailed or not current_valid:
        if min_version:
          min_because = [t for t in ranges.target_dependencies[target]
                         if self.jvm_version(t) == min_version]
          yield '  min={} because of dependencies:'.format(min_version)
          for dep in sorted(min_because):
            yield '    {}'.format(dep.address.spec)
        if max_version:
          max_because = [t for t in ranges.target_dependees[target]
                         if self.jvm_version(t) == max_version]
          yield '  max={} because of dependees:'.format(max_version)
          for dep in sorted(max_because):
            yield '    {}'.format(dep.address.spec)
        yield ''

  def _changeable(self, change_name, can_change, change_getter):
    changes = {}
    for target in filter(self._is_relevant, self.jvm_targets):
      allowed = change_getter(target)
      if allowed is None or can_change(self.jvm_version(target), allowed):
        changes[target] = allowed
    yield 'The following {count} target{plural} can be {change}d:'.format(
      count=len(changes),
      change=change_name,
      plural='' if len(changes) == 1 else 's',
    )
    for target, allowed in sorted(changes.items()):
      yield '{target} can {change} to {allowed}'.format(target=target.address.spec,
                                                        allowed=allowed or '*',
                                                        change=change_name)
    yield ''

  def downgradeable(self):
    return self._changeable('downgrade',
                            can_change=lambda curr, nxt: curr > nxt,
                            change_getter=self._ranges.min_allowed_version.get)

  def upgradeable(self):
    return self._changeable('upgrade',
                            can_change=lambda curr, nxt: curr < nxt,
                            change_getter=self._ranges.max_allowed_version.get)

  def console_output(self, targets):
    if self.get_options().ranges:
      for line in self.possible_version_evaluation():
        yield line
    if self.get_options().upgradeable:
      for line in self.upgradeable():
        yield line
    if self.get_options().downgradeable:
      for line in self.downgradeable():
        yield line
