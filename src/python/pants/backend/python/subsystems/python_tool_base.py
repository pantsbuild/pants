# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.subsystem.subsystem import Subsystem


class PythonToolBase(Subsystem):
  """Base class for subsystems that configure a python tool to be invoked out-of-process."""

  # Subclasses must set.
  default_requirements = None
  default_entry_point = None
  # Subclasses need not override.
  default_interpreter_constraints = []

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--interpreter-constraints', type=list, advanced=True, fingerprint=True,
             default=cls.default_interpreter_constraints,
             help='Python interpreter constraints for this tool. An empty list uses the default '
                  'interpreter constraints for the repo.')
    register('--requirements', type=list, advanced=True, fingerprint=True,
             default=cls.default_requirements,
             help='Python requirement strings for the tool.')
    register('--entry-point', type=str, advanced=True, fingerprint=True,
             default=cls.default_entry_point,
             help='The main module for the tool.')

  def get_interpreter_constraints(self):
    return self.get_options().interpreter_constraints

  def get_requirement_specs(self):
    return self.get_options().requirements

  def get_entry_point(self):
    return self.get_options().entry_point
