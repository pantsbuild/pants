# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
from textwrap import dedent

from pants.base.build_environment import get_default_pants_config_file
from pants.base.exceptions import TaskError
from pants.task.task import Task
from pants.version import VERSION as pants_version


class GeneratePantsIni(Task):
  """Generate pants.ini with sensible defaults."""

  def execute(self):
    pants_ini_path = get_default_pants_config_file()
    python_version = ".".join(str(v) for v in sys.version_info[:2])
    pants_ini_content = dedent("""\
      [GLOBAL]
      pants_version: {}
      pants_runtime_python_version: {}
      """.format(pants_version, python_version)
    )

    if os.stat(pants_ini_path).st_size != 0:
      raise TaskError("{} is not empty. To update config values, please directly modify pants.ini. "
                      "For example, you may want to add these entries:\n\n{}".format(pants_ini_path, pants_ini_content))

    self.context.log.info(dedent("""\
      Adding sensible defaults to {}:
      * Pinning `pants_version` to `{}`.
      * Pinning `pants_runtime_python_version` to `{}`.
      """.format(pants_ini_path, pants_version, python_version)
    ))

    with open(pants_ini_path, "w") as f:
      f.write(pants_ini_content)

    self.context.log.info("You may modify these values directly in the file at any time, and "
                          "the ./pants script will detect the changes for you the next time you run it.")
    self.context.log.info("You are now ready to use Pants!")
