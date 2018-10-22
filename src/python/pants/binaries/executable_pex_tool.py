# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pex.pex import PEX
from pex.pex_builder import PEXBuilder

from pants.backend.python.subsystems.python_repos import PythonRepos
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.tasks.pex_build_util import dump_requirements
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_executable, safe_concurrent_creation
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


class ExecutablePexTool(Subsystem):

  entry_point = None

  base_requirements = []

  # NB: The `dump_requirements` method uses PythonSetup and PythonRepos (the global instances)
  # behind your back - you need to declare subsystem dependencies on these two as things stand to be
  # safe.
  @classmethod
  def subsystem_dependencies(cls):
    return super(ExecutablePexTool, cls).subsystem_dependencies() + (PythonRepos, PythonSetup)

  @memoized_property
  def python_setup(self):
    return PythonSetup.global_instance()

  def bootstrap(self, interpreter, pex_file_path, extra_reqs=None):
    # Caching is done just by checking if the file at the specified path is already executable.
    if not is_executable(pex_file_path):
      with safe_concurrent_creation(pex_file_path) as safe_path:
        builder = PEXBuilder(interpreter=interpreter)
        all_reqs = list(self.base_requirements) + list(extra_reqs or [])
        dump_requirements(builder, interpreter, all_reqs, logger, platforms=['current'])
        if self.entry_point:
          builder.set_entry_point(self.entry_point)
        builder.build(safe_path)

    return PEX(pex_file_path, interpreter)
