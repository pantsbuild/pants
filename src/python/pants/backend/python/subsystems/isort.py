# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class Isort(PythonToolBase):
  options_scope = 'isort'
  default_requirements = ['isort==4.3.4', 'setuptools']
  default_entry_point = 'isort.main'

  @classmethod
  def register_options(cls, register):
    super(Isort, cls).register_options(register)
    register('--version', default='4.3.4', advanced=True, fingerprint=True,
             help='The version of isort to use.',
             removal_version='1.15.0.dev2',
             removal_hint='Use --requirements instead.')
    register('--additional-requirements', default=['setuptools'], type=list,
             advanced=True, fingerprint=True,
             help='Additional undeclared dependencies of the requested isort version.',
             removal_version='1.15.0.dev2',
             removal_hint='Use --requirements instead.')

  # TODO: Delete this method when the deprecated options are removed.
  def get_requirement_specs(self):
    opts = self.get_options()
    if opts.is_default('version') and opts.is_default('additional_requirements'):
      return super(Isort, self).get_requirement_specs()
    return [
      'isort=={}'.format(self.get_options().version)
    ] + self.get_options().additional_requirements
