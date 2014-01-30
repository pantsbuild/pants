# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import collections
import copy

from functools import partial

from twitter.common.collections import maybe_list, OrderedSet

from twitter.pants.base.target import Target, TargetDefinitionException

from .anonymous import AnonymousDeps
from .external_dependency import ExternalDependency
from .jar_dependency import JarDependency
from .util import resolve


class InternalTarget(Target):
  """A baseclass for targets that support an optional dependency set."""

  class CycleException(Exception):
    """Thrown when a circular dependency is detected."""
    def __init__(self, cycle):
      Exception.__init__(self, 'Cycle detected:\n\t%s' % (
          ' ->\n\t'.join(str(target.address) for target in cycle)
      ))

  @classmethod
  def sort_targets(cls, internal_targets):
    """Returns the targets that internal_targets depend on sorted from most dependent to least."""
    roots = OrderedSet()
    inverted_deps = collections.defaultdict(OrderedSet)  # target -> dependent targets
    visited = set()
    path = OrderedSet()

    def invert(target):
      if target in path:
        path_list = list(path)
        cycle_head = path_list.index(target)
        cycle = path_list[cycle_head:] + [target]
        raise cls.CycleException(cycle)
      path.add(target)
      if target not in visited:
        visited.add(target)
        if getattr(target, 'internal_dependencies', None):
          for internal_dependency in target.internal_dependencies:
            if hasattr(internal_dependency, 'internal_dependencies'):
              inverted_deps[internal_dependency].add(target)
              invert(internal_dependency)
        else:
          roots.add(target)
      path.remove(target)

    for internal_target in internal_targets:
      invert(internal_target)

    ordered = []
    visited.clear()

    def topological_sort(target):
      if target not in visited:
        visited.add(target)
        if target in inverted_deps:
          for dep in inverted_deps[target]:
            topological_sort(dep)
        ordered.append(target)

    for root in roots:
      topological_sort(root)

    return ordered

  @classmethod
  def coalesce_targets(cls, internal_targets, discriminator):
    """Returns a list of targets internal_targets depend on sorted from most dependent to least and
    grouped where possible by target type as categorized by the given discriminator.
    """

    sorted_targets = filter(discriminator, cls.sort_targets(internal_targets))

    # can do no better for any of these:
    # []
    # [a]
    # [a,b]
    if len(sorted_targets) <= 2:
      return sorted_targets

    # For these, we'd like to coalesce if possible, like:
    # [a,b,a,c,a,c] -> [a,a,a,b,c,c]
    # adopt a quadratic worst case solution, when we find a type change edge, scan forward for
    # the opposite edge and then try to swap dependency pairs to move the type back left to its
    # grouping.  If the leftwards migration fails due to a dependency constraint, we just stop
    # and move on leaving "type islands".
    current_type = None

    # main scan left to right no backtracking
    for i in range(len(sorted_targets) - 1):
      current_target = sorted_targets[i]
      if current_type != discriminator(current_target):
        scanned_back = False

        # scan ahead for next type match
        for j in range(i + 1, len(sorted_targets)):
          look_ahead_target = sorted_targets[j]
          if current_type == discriminator(look_ahead_target):
            scanned_back = True

            # swap this guy as far back as we can
            for k in range(j, i, -1):
              previous_target = sorted_targets[k - 1]
              mismatching_types = current_type != discriminator(previous_target)
              not_a_dependency = look_ahead_target not in previous_target.internal_dependencies
              if mismatching_types and not_a_dependency:
                sorted_targets[k] = sorted_targets[k - 1]
                sorted_targets[k - 1] = look_ahead_target
              else:
                break  # out of k

            break  # out of j

        if not scanned_back:  # done with coalescing the current type, move on to next
          current_type = discriminator(current_target)

    return sorted_targets

  def sort(self):
    """Returns a list of targets this target depends on sorted from most dependent to least."""
    return self.sort_targets([self])

  def coalesce(self, discriminator):
    """Returns a list of targets this target depends on sorted from most dependent to least and
    grouped where possible by target type as categorized by the given discriminator.
    """
    return self.coalesce_targets([self], discriminator)

  def __init__(self, name, dependencies, exclusives=None):
    """
    :param string name: The name of this module target, addressable via pants via the
      portion of the spec following the colon.
    :param dependencies: List of :class:`twitter.pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    """
    Target.__init__(self, name, exclusives=exclusives)
    self._injected_deps = []
    self.processed_dependencies = resolve(dependencies)

    self.add_labels('internal')
    self.dependency_addresses = OrderedSet()

    self._dependencies = OrderedSet()
    self._internal_dependencies = OrderedSet()
    self._jar_dependencies = OrderedSet()

    self._deps = self.processed_dependencies
    if dependencies:
      maybe_list(self.processed_dependencies,
                 expected_type=(ExternalDependency, AnonymousDeps, Target),
                 raise_type=partial(TargetDefinitionException, self))

    # TODO(John Sirois): XXX reconcile _post_constructs below with @property style delayed
    # resolution,

    # Defer dependency resolution after parsing the current BUILD file to allow for forward
    # references
    self._post_construct(self.update_dependencies, self.processed_dependencies)

    self._post_construct(self.inject_dependencies)

  def add_injected_dependency(self, spec):
    self._injected_deps.append(spec)

  def inject_dependencies(self):
    self.update_dependencies(resolve(self._injected_deps))

  @property
  def dependencies(self):
    self._maybe_apply_deps()
    return self._dependencies

  @property
  def internal_dependencies(self):
    self._maybe_apply_deps()
    return self._internal_dependencies

  @property
  def jar_dependencies(self):
    self._maybe_apply_deps()
    return self._jar_dependencies

  def _maybe_apply_deps(self):
    if self._deps is not None:
      self.update_dependencies(self._deps)
      self._deps = None

  def update_dependencies(self, dependencies):
    if dependencies:
      for dependency in dependencies:
        if hasattr(dependency, 'address'):
          self.dependency_addresses.add(dependency.address)
        if not hasattr(dependency, "resolve"):
          raise TargetDefinitionException(self, 'Cannot add %s as a dependency of %s'
                                                % (dependency, self))
        for resolved_dependency in dependency.resolve():
          if resolved_dependency.is_concrete and not self.valid_dependency(resolved_dependency):
            raise TargetDefinitionException(self, 'Cannot add %s as a dependency of %s'
                                                  % (resolved_dependency, self))
          self._dependencies.add(resolved_dependency)
          if isinstance(resolved_dependency, InternalTarget):
            self._internal_dependencies.add(resolved_dependency)
      self._jar_dependencies = OrderedSet(filter(lambda tgt: isinstance(tgt, JarDependency),
                                                 self._dependencies - self._internal_dependencies))

  def valid_dependency(self, dep):
    """Subclasses can over-ride to reject invalid dependencies."""
    return True

  def replace_dependency(self, dependency, replacement):
    self._dependencies.discard(dependency)
    self._internal_dependencies.discard(dependency)
    self._jar_dependencies.discard(dependency)
    self.update_dependencies([replacement])

  def _walk(self, walked, work, predicate=None):
    Target._walk(self, walked, work, predicate)
    for dep in self.dependencies:
      if isinstance(dep, Target) and not dep in walked:
        walked.add(dep)
        if not predicate or predicate(dep):
          additional_targets = work(dep)
          dep._walk(walked, work, predicate)
          if additional_targets:
            for additional_target in additional_targets:
              additional_target._walk(walked, work, predicate)

  def _propagate_exclusives(self):
    # Note: this overrides Target._propagate_exclusives without
    # calling the supermethod. Targets in pants do not necessarily
    # have a dependencies field, or ever have their dependencies
    # available at all pre-resolve. Subtypes of InternalTarget, however,
    # do have well-defined dependency lists in their dependencies field,
    # so we can do a better job propagating their exclusives quickly.
    if self.exclusives is not None:
      return
    self.exclusives = copy.deepcopy(self.declared_exclusives)
    for t in self.dependencies:
      if isinstance(t, Target):
        t._propagate_exclusives()
        self.add_to_exclusives(t.exclusives)
      elif hasattr(t, "declared_exclusives"):
        self.add_to_exclusives(t.declared_exclusives)
