# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys

from pants.base.exceptions import TaskError
from pants.task.task import Task
from pants.version import VERSION as pants_version


class GeneratePantsIni(Task):
  """Generate pants.ini with sensible defaults."""

  PANTS_INI = "pants.ini"

  def execute(self):
    if os.stat(self.PANTS_INI).st_size != 0:
      raise TaskError("{} is not empty! This goal is only meant for first-time "
                      "users. Please update config values by directly modifying the file.".format(self.PANTS_INI))

    python_version = ".".join(str(v) for v in sys.version_info[:2])

    self.context.log.info("Adding sensible defaults to the `{}` config file:".format(self.PANTS_INI))
    self.context.log.info("* Pinning `pants_version` to `{}`.".format(pants_version))
    self.context.log.info("* Pinning `pants_runtime_python_version` to `{}`.".format(python_version))

    with open(self.PANTS_INI, "w") as f:
      f.write("""\
        [GLOBAL]
        pants_version: {}
        pants_runtime_python_version: {}
        """.format(pants_version, python_version)
      )

    self.context.log.info("{} is now set up. You may modify its values directly in the file at any time, and "
                          "the ./pants script will detect the changes for you.".format(self.PANTS_INI))
    self.context.log.info("You are now ready to use Pants!")
