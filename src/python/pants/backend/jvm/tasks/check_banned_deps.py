# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.task.task import Task


class BannedDependencyException(Exception):
  pass


class CheckBannedDeps(Task):
  """
  This task ensures that a target does not depend on banned dependencies.
  """

  @classmethod
  def register_options(cls, register):
    super(CheckBannedDeps, cls).register_options(register)
    # If this flag changes, the debug message below should change too.
    register('--skip', type=bool, fingerprint=True, default=True,
      help='Do not perform the operations if this is active')

  @classmethod
  def prepare(cls, options, round_manager):
    super(CheckBannedDeps, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  @staticmethod
  def relevant_targets(target):
    """
    Modify this method when the criteria changes
    (e.g. the target itself should be included in the checks).
    """
    return set(target.dependencies)

  def execute(self):
    if not self.get_options().skip:
      bad_elements = self.check_graph()
      self.context.log.debug("BL: Bad elements {}".format(bad_elements))
      if bad_elements:
        raise BannedDependencyException("ERROR!")
    else:
      self.context.log.debug("Skipping banned dependency checks. To enforce this, enable the --no-compile-check-banned-deps-skip flag")

  def check_graph(self):
    constraints_for = {}  # Map<Address, Set<Constraint>>
    roots_for = {}  # Map<Dep, Set<Root>>

    def process_dep(root, dep):
      if roots_for.get(dep.address.spec):
        roots_for[dep].add(root)
      else:
        roots_for[dep] = {root}
      constraint_declaration = dep.payload.get_field_value("dependency_constraints")
      if constraint_declaration:
        constraints_for[root] |= constraint_declaration.constraints

    # Every root has independent constraints
    for root in self.context.target_roots:
      constraints_for[root] = set([])
      # Gather constraints by traversing the graph once.
      root.walk(
        lambda dep: process_dep(root, dep)
      )

    # Apply constraints to every dependency
    # We assume the roots for every dep are going to be small,
    # Each iteration of the loop should take O(|roots| * |constraints_for[rx]|).
    # Ideally, we would preconopute constraints_for[dep],
    # and make this not relative to |roots_for[dep]|
    errors = []
    for (dep, roots) in roots_for.items():
      for root in roots:
        for constraint in constraints_for[root]:
          errors += constraint.check_target(root, self.context, dep)

    #
    # def check_dependency(dep, root):
    #   already_checked = checked_constraints.get(dep.address.spec) or set([])
    #   constraints_to_apply = constraints - already_checked
    #   for constraint in constraints_to_apply:
    #     self.errors += constraint.check_target(root, self.context, dep)
    #   checked_constraints[dep.address.spec] = constraints | already_checked
    #
    # def needs_to_expand(dep, root):
    #   self.context.build_graph
    #   if dep == root:
    #     return True
    #   if checked_constraints.has_key(dep.address.spec):
    #     return len(checked_constraints[dep.address.spec] - constraints_for[root.address.spec]) != 0
    #   return True
    #
    # for root in self.context.target_roots:
    #   # Walk the graph, applying the constraints and finding errors
    #   root.walk(
    #     work=lambda dep: check_dependency(dep, root),
    #     # predicate=lambda dep: needs_to_expand(dep, root),
    #   )

    return errors
