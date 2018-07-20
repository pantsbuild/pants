# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.tasks.pex_build_util import dump_requirements
from pants.backend.python.tasks.wrapped_pex import WrappedPEX
from pants.base.build_environment import get_pants_cachedir
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_concurrent_creation
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class Conan(Subsystem):
  """Pex binary for the conan package manager."""
  options_scope = 'conan'
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
  def implementation_version(cls):
    return super(Conan, cls).implementation_version() + [('Conan', 0)]

  @classmethod
  def register_options(cls, register):
    super(Conan, cls).register_options(register)
    register('--conan-requirements', type=list, default=cls.default_conan_requirements,
             advanced=True, help='The requirements used to build the conan client pex.')

  class ConanBinary(datatype(['pex'])):
    """A `conan` PEX binary."""
    pass

  def bootstrap_conan(self):
    pex_info = PexInfo.default()
    pex_info.entry_point = 'conans.conan'
    conan_bootstrap_dir = os.path.join(get_pants_cachedir(), 'conan_support')
    conan_pex_path = os.path.join(conan_bootstrap_dir, 'conan_binary')
    interpreter = PythonInterpreter.get()
    if os.path.exists(conan_pex_path):
      conan_binary = WrappedPEX(PEX(conan_pex_path, interpreter))
      return self.ConanBinary(pex=conan_binary)
    else:
      with safe_concurrent_creation(conan_pex_path) as safe_path:
        builder = PEXBuilder(safe_path, interpreter, pex_info=pex_info)
        reqs = [PythonRequirement(req) for req in self.get_options().conan_requirements]
        dump_requirements(builder, interpreter, reqs, logger)
        builder.freeze()
      conan_binary = WrappedPEX(PEX(conan_pex_path, interpreter))
      return self.ConanBinary(pex=conan_binary)
