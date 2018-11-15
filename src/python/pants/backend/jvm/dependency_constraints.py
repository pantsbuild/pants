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
    self.constraints = constraints

  def _compute_fingerprint(self):
    return combine_hashes([c.fingerprint() for c in self.constraints])

class BannedDependencyException(Exception):
  pass


class Constraint(PayloadField):
  """Representation of a constraint on the target's dependencies."""

  def check_target(self, target, task_context, target_under_test):
    """
    Check whether a given target complies with this constraint.

    Note that there are constraints that apply to targets, and constraints that apply to classes.
    Therefore, this flow is left general in purpose to accomodate for both requirements.
    :param target: Target to check.
    :param task_context: Context of the task, to extract from it any relevant information.
    :param target_under_test: The target that we want the constraint to apply to.
    :return:
    """
    items = self.get_collection_to_constrain(task_context, target_under_test)
    bad_elements = [item for item in items if self.predicate(item)]
    if bad_elements:
      raise BannedDependencyException(self.get_error_message(target, target_under_test, bad_elements))

  def get_collection_to_constrain(self, context, target_under_test):
    """
    Method to specify what the constraint applies to.
    It will usually be targets, but there are some that apply to classes.
    Overriding this method allows the user to express that.
    """
    return [target_under_test]

  @abstractmethod
  def get_error_message(self, target, target_under_test, bad_elements):
    """Error message to show when a constraint bans an element.
    :param target Target that was examined.
    :param target_under_test Target that was tested by the constraint.
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
  def _get_classes_in_classpath(context, target):
    classpath = context.products.get_data("runtime_classpath")
    analyzer = JvmDependencyAnalyzer(get_buildroot(), classpath)
    return analyzer.classes_for_targets([target])

  def get_collection_to_constrain(self, context, target_under_test):
    # TODO we actually ignore this, bit since this is a method override, python guides said that we should call it.
    super(JvmPackageConstraint, self).get_collection_to_constrain(context, target_under_test)
    return self._get_classes_in_classpath(context, target_under_test)

  def get_error_message(self, target, checked_target, banned_classes):
    return 'Target {} bans package "{}", which bans target {} with classes ({})'.format(
      target.target_base,
      self.banned_package_name,
      checked_target.target_base,
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

  def get_error_message(self, target, checked_target, bad_element):
    return 'Target {} has baned tag "{}", but these target has it {}'.format(
      target.target_base,
      self.banned_tag_name,
      checked_target.target_base
    )

  def predicate(self, target):
    return self.banned_tag_name in target.tags

class TestDependencies(Constraint):
  """Check that this target does not depend on test targets"""

  def __init__(self):
    self.name = "test_dependencies"

  def _compute_fingerprint(self):
    return stable_json_hash(self.name)

  def get_error_message(self, target, checked_target, bad_element):
    return 'Target {} has test dependencies on target {}'.format(
      target.target_base,
      checked_target.target_base
    )

  def predicate(self, dependency):
    return isinstance(dependency, JUnitTests)
