# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


logger = logging.getLogger(__name__)


class Conan(PythonToolBase):
  options_scope = 'conan'
  default_requirements = [
    'conan==1.9.2',
    # NB: Only versions of pylint below `2.0.0` support use in python 2.
    'pylint==1.9.3',
  ]
  default_entry_point = 'conans.conan'
  default_interpreter_constraints = ['CPython>=2.7,<4']

  @classmethod
  def register_options(cls, register):
    super(Conan, cls).register_options(register)
    register('--conan-requirements', type=list,
             default=Conan.default_requirements,
             advanced=True, fingerprint=True,
             help='The requirements used to build the conan client pex.',
             removal_version='1.16.0.dev2',
             removal_hint='Use --requirements instead.')

  # TODO: Delete this method when the deprecated options are removed.
  def get_requirement_specs(self):
    opts = self.get_options()
    if opts.is_default('conan_requirements'):
      return super(Conan, self).get_requirement_specs()
    return opts.conan_requirements
