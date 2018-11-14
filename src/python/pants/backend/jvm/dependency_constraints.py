# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from abc import abstractmethod

from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.base.build_environment import get_buildroot
from pants.base.hash_utils import stable_json_hash
from pants.base.payload_field import PayloadField, combine_hashes


class DependencyConstraints(PayloadField):
  """
  Representation of a list of constraints.
  For now, it only handles jvm-style dependency constraints in the classpath.
  """

  def __init__(self, constraints):
    """
    We keep the direct/transitive separation since that might be useful
    if we decide to switch to the graph-based approach.

    :param direct: Constraints on direct dependencies.
    :param transitive: Constraints on transitive dependencies.
    """
    self._constraints = constraints

  def _compute_fingerprint(self):
    return combine_hashes([c.fingerprint() for c in self._constraints])

  def check_all(self, target, task_context):
    # TODO Execution is currently n^2, which is not very relevant because this is behind a flag.

    # TODO Eventually, the next three lines should be moved out of here,
    #      and the `classes_relevant_to_target` parameter removed from `check_target`.
    #      Ideally we would have the same interface for all the subclasses of DependencyConstraint,
    #      which I think should be check_target(target, task_context)
    relevant_targets = DependencyConstraints.relevant_targets(target)
    for constraint in self._constraints:
      constraint.check_target(target, task_context, relevant_targets)

  @staticmethod
  def relevant_targets(target):
    """
    Modify this method when the criteria changes
    (i.e. the target itself should be included in the checks).
    """
    return target.dependencies


class BannedDependencyException(Exception):
  pass


class Constraint(PayloadField):
  """Representation of a constraint on the target's dependencies."""

  @abstractmethod
  def check_target(self, target, task_context, relevant_targets):
    """
    Check whether a given target complies with this constraint.
    :param target: Target to check.
    :param task_context: Context of the task, to extract from it any relevant information.
    :param relevant_targets: The set of targets that we have to check.
    :return:
    """
    pass


class JvmPackageConstraint(Constraint):

  def __init__(self, name):
    self.banned_package_name = name

  def _get_classes_in_classpath(self, context, relevant_targets):
    classpath = context.products.get_data("runtime_classpath")
    analyzer = JvmDependencyAnalyzer(get_buildroot(), classpath)
    return analyzer.classes_for_targets(relevant_targets)

  def check_target(self, target, context, relevant_targets):
    relevant_classes = self._get_classes_in_classpath(context, relevant_targets)
    banned_classes = [c for c in relevant_classes if c.startswith(self.banned_package_name)]
    if banned_classes:
      raise BannedDependencyException(
        'Target {} uses rule "{}" to ban classes ({})'.format(
          target.target_base,
          self.banned_package_name,
          ", ".join(banned_classes)
        ))

  def _compute_fingerprint(self):
    return stable_json_hash(self.banned_package_name)


class Tag(Constraint):
  """Representation of the ban of a tag"""

  def __init__(self, banned_tag_name):
    self.banned_tag_name = banned_tag_name

  def _has_bad_tag(self, target):
    return self.banned_tag_name in target.tags

  def check_target(self, target, task_context, relevant_targets):
    forbidden_targets = [t for t in relevant_targets if self._has_bad_tag(t)]
    if forbidden_targets:
      raise BannedDependencyException(
        'Target {} has baned tag "{}", but these targets have it ({})'.format(
          target.target_base,
          self.banned_tag_name,
          ", ".join([t.target_base for t in forbidden_targets])
        ))

  def _compute_fingerprint(self):
    return stable_json_hash(self.banned_tag_name)


class TestDependencies(Constraint):
  """Check that this target does not depend on test targets"""

  def __init__(self):
    self.name = "test_dependencies"

  def _is_test_dependency(self, dependency):
    return isinstance(dependency, JUnitTests)

  def check_target(self, target, task_context, relevant_targets):
    forbidden_targets = [t for t in relevant_targets if self._is_test_dependency(t)]
    if forbidden_targets:
      raise BannedDependencyException(
        'Target {} has test dependencies on targets ({})'.format(
          target.target_base,
          ", ".join([t.target_base for t in forbidden_targets])
        ))

  def _compute_fingerprint(self):
    return stable_json_hash(self.name)
