# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.binaries.binary_tool import NativeTool
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


class BuildozerBinary(NativeTool):
  # Note: Not in scope 'buildozer' because that's the name of the singleton task
  # that runs buildozer.
  options_scope = 'buildozer-binary'
  name = 'buildozer'
  default_version = '0.6.0.dce8b3c287652cbcaf43c8dd076b3f48c92ab44c'

  replaces_scope = 'buildozer'
  replaces_name = 'version'

  def execute(self, buildozer_command, spec, context=None):
    try:
      subprocess.check_call([self.select(context), buildozer_command, spec], cwd=get_buildroot())
    except subprocess.CalledProcessError as err:
      if err.returncode == 3:
        logger.warn('{} ... no changes were made'.format(buildozer_command))
      else:
        raise TaskError('{} ... exited non-zero ({}).'.format(buildozer_command, err.returncode))
