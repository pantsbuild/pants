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

from twitter.common.collections import OrderedSet
import collections

from twitter.pants.base import Target

class InternalTarget_CycleException(Exception):
  """Thrown when a circular dependency is detected."""

  def __init__(self, precedents, cycle):
    Exception.__init__(self, 'Cycle detected along path:\n\t%s' % (
      ' ->\n\t'.join(str(target.address) for target in list(precedents) + [ cycle ])
    ))

class InternalTarget(Target):
  """A baseclass for targets that support an optional dependency set."""

  @classmethod
  def check_cycles(cls, internal_target):
    """Validates the given InternalTarget has no circular dependencies.  Raises CycleException if
    it does."""

    dep_stack = OrderedSet()

    def descend(internal_dep):
      if internal_dep in dep_stack:
        raise InternalTarget_CycleException(dep_stack, internal_dep)
      if hasattr(internal_dep, 'internal_dependencies'):
        dep_stack.add(internal_dep)
        for dep in internal_dep.internal_dependencies:
          descend(dep)
        dep_stack.remove(internal_dep)

    descend(internal_target)

  @classmethod
  def sort_targets(cls, internal_targets):
    """Returns a list of targets that internal_targets depend on sorted from most dependent to
    least."""

    roots = OrderedSet()
    inverted_deps = collections.defaultdict(OrderedSet) # target -> dependent targets
    visited = set()

    def invert(target):
      if target not in visited:
        visited.add(target)
        if target.internal_dependencies:
          for internal_dependency in target.internal_dependencies:
            if isinstance(internal_dependency, InternalTarget):
              inverted_deps[internal_dependency].add(target)
              invert(internal_dependency)
        else:
          roots.add(target)

    for internal_target in internal_targets:
      invert(internal_target)

    sorted = []
    visited.clear()

    def topological_sort(target):
      if target not in visited:
        visited.add(target)
        if target in inverted_deps:
          for dep in inverted_deps[target]:
            topological_sort(dep)
        sorted.append(target)

    for root in roots:
      topological_sort(root)

    return sorted

  @classmethod
  def coalesce_targets(cls, internal_targets):
    """Returns a list of targets internal_targets depend on sorted from most dependent to least and
    grouped where possible by target type."""

    sorted_targets = InternalTarget.sort_targets(internal_targets)

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
      if current_type != type(current_target):
        scanned_back = False

        # scan ahead for next type match
        for j in range(i + 1, len(sorted_targets)):
          look_ahead_target = sorted_targets[j]
          if current_type == type(look_ahead_target):
            scanned_back = True

            # swap this guy as far back as we can
            for k in range(j, i, -1):
              previous_target = sorted_targets[k - 1]
              mismatching_types = current_type != type(previous_target)
              not_a_dependency = look_ahead_target not in previous_target.internal_dependencies
              if mismatching_types and not_a_dependency:
                sorted_targets[k] = sorted_targets[k - 1]
                sorted_targets[k - 1] = look_ahead_target
              else:
                break # out of k

            break # out of j

        if not scanned_back: # done with coalescing the current type, move on to next
          current_type = type(current_target)

    return sorted_targets

  def sort(self):
    """Returns a list of targets this target depends on sorted from most dependent to least."""

    return InternalTarget.sort_targets([ self ])

  def coalesce(self):
    """Returns a list of targets this target depends on sorted from most dependent to least and
    grouped where possible by target type."""

    return InternalTarget.coalesce_targets([ self ])

  def __init__(self, name, dependencies, is_meta):
    Target.__init__(self, name, is_meta)

    self.resolved_dependencies = OrderedSet()
    self.internal_dependencies = OrderedSet()
    self.jar_dependencies = OrderedSet()

    self.update_dependencies(dependencies)

  def update_dependencies(self, dependencies):
    if dependencies:
      for dependency in dependencies:
        for resolved_dependency in dependency.resolve():
          self.resolved_dependencies.add(resolved_dependency)
          if isinstance(resolved_dependency, InternalTarget):
            self.internal_dependencies.add(resolved_dependency)
          self.jar_dependencies.update(resolved_dependency._as_jar_dependencies())

  def _walk(self, walked, work, predicate = None):
    Target._walk(self, walked, work, predicate)
    for dep in self.resolved_dependencies:
      if isinstance(dep, Target) and not dep in walked:
        walked.add(dep)
        if not predicate or predicate(dep):
          additional_targets = work(dep)
          dep._walk(walked, work, predicate)
          if additional_targets:
            for additional_target in additional_targets:
              additional_target._walk(walked, work, predicate)
