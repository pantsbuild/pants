# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.tasks.pex_build_util import dump_requirements
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_executable, safe_concurrent_creation


logger = logging.getLogger(__name__)


class ExecutablePexTool(Subsystem):

  entry_point = None

  base_requirements = []

  def bootstrap(self, interpreter, pex_file_path, extra_reqs=None):
    pex_info = PexInfo.default()
    if self.entry_point is not None:
      pex_info.entry_point = self.entry_point
    if is_executable(pex_file_path):
      return PEX(pex_file_path, interpreter)
    else:
      with safe_concurrent_creation(pex_file_path) as safe_path:
        builder = PEXBuilder(interpreter=interpreter, pex_info=pex_info)
        all_reqs = list(self.base_requirements) + list(extra_reqs or [])
        dump_requirements(builder, interpreter, all_reqs, logger)
        builder.build(safe_path)
      return PEX(pex_file_path, interpreter)
