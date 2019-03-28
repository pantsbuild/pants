# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import configparser
import logging
import os
import sys

from pants.base.exceptions import TaskError
from pants.task.task import Task
from pants.version import VERSION


logger = logging.getLogger(__name__)


class GeneratePantsIni(Task):
  """Generate pants.ini with sensible defaults."""

  PANTS_INI = "pants.ini"

  class CustomConfigParser(configparser.ConfigParser):
    """We monkey-patch the write() function to allow us to write entries in the style `key: value`, 
       rather than `key:value` or `key : value`."""

    def write(self, fp):
      # Refer to https://github.com/jaraco/configparser/blob/294a985b759bddd3505ace54ecf56da39c56a302/src/backports/configparser/__init__.py#L916
      # for the original source.
      delimiter = ": "
      if self._defaults:
        self._write_section(fp, self.default_section, self._defaults.items(), delimiter)
      for section in self._sections:
        self._write_section(fp, section, self._sections[section].items(), delimiter)

  def execute(self):
    if os.stat(self.PANTS_INI).st_size != 0:
      raise TaskError("{} is not empty! This goal is only meant for first-time "
                      "users. Please update config values by directly modifying the file.".format(self.PANTS_INI))

    pants_version = VERSION
    python_version = ".".join(str(v) for v in sys.version_info[:2])

    config = self.CustomConfigParser()
    logger.info("Adding sensible defaults to the `{}` config file:".format(self.PANTS_INI))

    logger.info("* Pinning `pants_version` to `{}`.".format(pants_version))
    config["GLOBAL"] = {"pants_version": pants_version}
    if python_version is not None:
      logger.info("* Pinning `pants_runtime_python_version` to `{}`.".format(python_version))
      config["GLOBAL"]["pants_runtime_python_version"] = python_version

    with open(self.PANTS_INI, 'w') as f:
      config.write(f)

    logger.info("{} is now set up. You may modify its values directly in the file at any time, and "
                "the ./pants script will detect the changes for you.".format(self.PANTS_INI))
    logger.info("You are now ready to use Pants!")
