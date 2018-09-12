# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pants.backend.python.python_requirement import PythonRequirement
from pants.binaries.executable_pex_tool import ExecutablePexTool
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


class Conan(ExecutablePexTool):
  """Pex binary for the conan package manager."""
  options_scope = 'conan'

  entry_point = 'conans.conan'

  # TODO: It would be great if these requirements could be drawn from a BUILD file (potentially with
  # a special target specified in BUILD.tools)?
  default_conan_requirements = (
    'conan==1.4.4',
    'PyJWT>=1.4.0, <2.0.0',
    'requests>=2.7.0, <3.0.0',
    'colorama>=0.3.3, <0.4.0',
    'PyYAML>=3.11, <3.13.0',
    'patch==1.16',
    'fasteners>=0.14.1',
    'six>=1.10.0',
    'node-semver==0.2.0',
    'distro>=1.0.2, <1.2.0',
    'pylint>=1.8.1, <1.9.0',
    'future==0.16.0',
    'pygments>=2.0, <3.0',
    'astroid>=1.6, <1.7',
    'deprecation>=2.0, <2.1'
  )

  @classmethod
  def register_options(cls, register):
    super(Conan, cls).register_options(register)
    register('--conan-requirements', type=list, default=cls.default_conan_requirements,
             advanced=True, help='The requirements used to build the conan client pex.')

  @classmethod
  def implementation_version(cls):
    return super(Conan, cls).implementation_version() + [('Conan', 0)]

  @memoized_property
  def base_requirements(self):
    return [PythonRequirement(req) for req in self.get_options().conan_requirements]
