# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.subsystem.subsystem import Subsystem


class PythonToolBase(Subsystem):
  """Base class for subsystems that configure a python tool to be invoked out-of-process."""

  # Subclasses must set.
  default_requirements = None
  default_entry_point = None

  @classmethod
  def register_options(cls, register):
    super(PythonToolBase, cls).register_options(register)
    register('--requirements', type=list, advanced=True, fingerprint=True,
             default=cls.default_requirements,
             help='Python requirement strings for the tool.')
    register('--entry-point', type=str, advanced=True, fingerprint=True,
             default=cls.default_entry_point,
             help='The main module for the tool.')

  def get_requirement_specs(self):
    return self.get_options().requirements

  def get_entry_point(self):
    return self.get_options().entry_point
