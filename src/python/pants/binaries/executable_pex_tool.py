# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
from abc import abstractproperty
from builtins import str

from future.utils import text_type
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.tasks.pex_build_util import dump_requirements
from pants.binaries.binary_util import BinaryRequest, BinaryUtil
from pants.engine.fs import PathGlobs, PathGlobsAndRoot
from pants.fs.archive import XZCompressedTarArchiver, create_archiver
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_concurrent_creation
from pants.util.memo import memoized_method, memoized_property


logger = logging.getLogger(__name__)


class ExecutablePexTool(Subsystem):

  entry_point = None

  @abstractproperty
  def pex_tool_requirements(self): pass

  def bootstrap(self, interpreter, pex_file_path):
    pex_info = PexInfo.default()
    if self.entry_point is not None:
      pex_info.entry_point = self.entry_point
    if os.path.exists(pex_file_path):
      return PEX(pex_file_path, interpreter)
    else:
      with safe_concurrent_creation(pex_file_path) as safe_path:
        builder = PEXBuilder(safe_path, interpreter, pex_info=pex_info)
        reqs = self.pex_tool_requirements
        dump_requirements(builder, interpreter, reqs, logger)
        builder.freeze()
      return PEX(pex_file_path, interpreter)
