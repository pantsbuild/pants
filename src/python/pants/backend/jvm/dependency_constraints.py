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
    # TODO Execution is currently n^2.
    relevant_targets = DependencyConstraints.relevant_targets(target)
    for constraint in self._constraints:
      constraint.check_target(target, task_context, relevant_targets)

  @staticmethod
  def relevant_targets(target):
    """
    Modify this method when the criteria changes
    (e.g. the target itself should be included in the checks).
    """
    return target.dependencies


class BannedDependencyException(Exception):
  pass


class Constraint(PayloadField):
  """Representation of a constraint on the target's dependencies."""

  def check_target(self, target, task_context, relevant_targets):
    """
    Check whether a given target complies with this constraint.

    Note that there are constraints that apply to targets, and constraints that apply to classes.
    Therefore, this flow is left general in purpose to accomodate for both requirements.
    :param target: Target to check.
    :param task_context: Context of the task, to extract from it any relevant information.
    :param relevant_targets: The set of targets that we have to check.
    :return:
    """
    items = self.get_collection_to_constrain(task_context, relevant_targets)
    bad_elements = [item for item in items if self.predicate(item)]
    if bad_elements:
      raise BannedDependencyException(self.get_error_message(target, bad_elements))

  def get_collection_to_constrain(self, context, relevant_targets):
    """
    Method to specify what the constraint applies to.
    It will usually be targets, but there are some that apply to classes.
    Overriding this method allows the user to express that.
    """
    return relevant_targets

  @abstractmethod
  def get_error_message(self, target, bad_elements):
    """Error message to show when a constraint bans an element.
    :param target Target that was examined.
    :param bad_elements Elements that were banned by the constraint.
                        These may be classes, targets or something else.
    :return A string with the error message.
    """
    pass

  @abstractmethod
  def predicate(self, item):
    """
    A function to determine if an item is banned by this constraint.
    :param item an intem of the type returned by get_collection_to_constrain
    :return True if the item is banned, False otherwise.
    """
    pass


class JvmPackageConstraint(Constraint):

  def __init__(self, name):
    self.banned_package_name = name

  @staticmethod
  def _get_classes_in_classpath(context, relevant_targets):
    classpath = context.products.get_data("runtime_classpath")
    analyzer = JvmDependencyAnalyzer(get_buildroot(), classpath)
    return analyzer.classes_for_targets(relevant_targets)

  def get_collection_to_constrain(self, context, relevant_targets):
    # TODO we actually ignore this, bit since this is a method override, python guides said that we should call it.
    super(JvmPackageConstraint, self).get_collection_to_constrain(context, relevant_targets)
    return self._get_classes_in_classpath(context, relevant_targets)

  def get_error_message(self, target, banned_classes):
    return 'Target {} uses rule "{}" to ban classes ({})'.format(
      target.target_base,
      self.banned_package_name,
      ", ".join(banned_classes)
    )

  def predicate(self, item):
    return item.startswith(self.banned_package_name)

  def _compute_fingerprint(self):
    return stable_json_hash(self.banned_package_name)


class Tag(Constraint):
  """Representation of the ban of a tag"""

  def __init__(self, banned_tag_name):
    self.banned_tag_name = banned_tag_name

  def _compute_fingerprint(self):
    return stable_json_hash(self.banned_tag_name)


  def get_error_message(self, target, forbidden_targets):
    return 'Target {} has baned tag "{}", but these targets have it ({})'.format(
      target.target_base,
      self.banned_tag_name,
      ", ".join([t.target_base for t in forbidden_targets])
    )

  def predicate(self, target):
    return self.banned_tag_name in target.tags

class TestDependencies(Constraint):
  """Check that this target does not depend on test targets"""

  def __init__(self):
    self.name = "test_dependencies"

  def _compute_fingerprint(self):
    return stable_json_hash(self.name)

  def get_error_message(self, target, forbidden_targets):
    return 'Target {} has test dependencies on targets ({})'.format(
      target.target_base,
      ", ".join([t.target_base for t in forbidden_targets])
    )

  def predicate(self, dependency):
    return isinstance(dependency, JUnitTests)
