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
    'conan==1.8.2',
    'typed_ast<1.1.0',  # Remove typed_ast when Pants runs with Python 3 by default.
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
