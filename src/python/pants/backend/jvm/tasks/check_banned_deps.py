from abc import abstractmethod

from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.python.targets.python_tests import PythonTests
from pants.task.task import Task
from pants.base.payload_field import combine_hashes, PayloadField, stable_json_hash
from pants.backend.jvm.tasks.jvm_dependency_analyzer import JvmDependencyAnalyzer
from pants.base.build_environment import get_buildroot

class DependencyConstraints(PayloadField):
  """
  Representation of a list of constraints.
  For now, it only handles jvm-style dependency constraints in the classpath.
  """
  def __init__(self, direct=None, transitive=None):
    """
    We keep the direct/transitive separation since that might be useful
    if we decide to switch to the graph-based approach.

    :param direct: Constraints on direct dependencies.
    :param transitive: Constraints on transitive dependencies.
    """
    self._constraints = direct + transitive

  def _compute_fingerprint(self):
     return combine_hashes([c.fingerprint() for c in self._constraints])

  def check_all(self, target, task_context):
    # TODO Eventually, the next three lines should be moved out of here,
    #      and the `classes_relevant_to_target` parameter removed from `check_target`.
    #      Ideally we would have the same interface for all the subclasses of DependencyConstraint,
    #      which I think should be check_target(target, task_context)
    classpath = task_context.products.get_data("runtime_classpath")
    analyzer = JvmDependencyAnalyzer(get_buildroot(), classpath)
    classes_relevant_to_target = analyzer.classes_for_targets(DependencyConstraints.relevant_targets(target))
    for constraint in self._constraints:
      constraint.check_target(target, task_context, classes_relevant_to_target)

  @staticmethod
  def relevant_targets(target):
    """
    Modify this method when the criteria changes
    (i.e. the target itself should be included in the checks).
    """
    return target.dependencies

class DependencyConstraint(object):
  """Umbrella to hold the Constraint class hierarchy.

  Has no functionality, but allows targets to use syntax like
    `DependencyConstraint.JvmPackageConstraint("com.google")`
  """
  class BannedDependencyException(Exception):
    pass

  class Constraint(PayloadField):
    """Representation of a constraint on the target's dependencies."""
    @abstractmethod
    def check_target(self, target, task_context, classes_relevant_to_target):
      pass

  class JvmPackageConstraint(Constraint):
    def __init__(self, name):
      self.banned_package_name = name

    def check_target(self, target, context, classes_relevant_to_target):
      """
      Check whether a given target complies with this constraint.
      :param target: Target to check.
      :param task_context: Context of the task, to extract from it any relevant information.
      :param classes_relevant_to_target: Fully qualified names of the classes in the target and its dependencies.
      :return:
      """
      banned_classes = [c for c in classes_relevant_to_target if c.startswith(self.banned_package_name)]
      if banned_classes:
        raise DependencyConstraint.BannedDependencyException(
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

    def check_target(self, target, task_context, classes_relevant_to_target):
      relevant_targets = DependencyConstraints.relevant_targets(target)
      forbidden_targets = [t for t in relevant_targets if self._has_bad_tag(t)]
      if forbidden_targets:
        raise DependencyConstraint.BannedDependencyException(
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
      return isinstance(dependency, (PythonTests, JUnitTests))

    def check_target(self, target, task_context, classes_relevant_to_target):
      relevant_targets = DependencyConstraints.relevant_targets(target)
      forbidden_targets = [t for t in relevant_targets if self._is_test_dependency(t)]
      if forbidden_targets:
        raise DependencyConstraint.BannedDependencyException(
          'Target {} has test dependencies on targets ({})'.format(
            target.target_base,
            ", ".join([t.target_base for t in forbidden_targets])
          ))

    def _compute_fingerprint(self):
      return stable_json_hash(self.name)

class CheckBannedDeps(Task):
  """
  This task ensures that a target does not depend on banned dependencies.
  """

  @classmethod
  def register_options(cls, register):
    super(CheckBannedDeps, cls).register_options(register)
    # If this flag changes, the debug message below should change too.
    register('--enforce', type=bool, fingerprint=True,
      help='Only perform the operations if this is active')

  @classmethod
  def prepare(cls, options, round_manager):
    super(CheckBannedDeps, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  def execute(self):
    if self.get_options().enforce:
      for target in self.context.targets():
        constraints = target.payload.get_field_value("dependency_constraints")
        if constraints:
          constraints.check_all(target, self.context)
    else:
      self.context.log.debug("Skipping banned dependency checks. To enforce this, enable the --compile-check-banned-deps-enforce flag")
