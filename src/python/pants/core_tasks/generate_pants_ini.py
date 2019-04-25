# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os.path
from textwrap import dedent

from pants.base.build_environment import get_default_pants_config_file
from pants.base.exceptions import TaskError
from pants.task.console_task import ConsoleTask
from pants.version import VERSION as pants_version


class GeneratePantsIni(ConsoleTask):
  """Generate pants.ini with sensible defaults."""

  def console_output(self, _targets):
    pants_ini_path = get_default_pants_config_file()
    pants_ini_content = dedent("""\
      [GLOBAL]
      pants_version: {}
      """.format(pants_version)
    )

    if os.path.isfile(pants_ini_path):
      raise TaskError("{} already exists. To update config values, please directly modify pants.ini. "
                      "For example, you may want to add these entries:\n\n{}".format(pants_ini_path, pants_ini_content))

    yield dedent("""\
      Adding sensible defaults to {}:
      * Pinning `pants_version` to `{}`.
      """.format(pants_ini_path, pants_version)
    )

    with open(pants_ini_path, "w") as f:
      f.write(pants_ini_content)

    yield ("You may modify these values directly in the file at any time. "
           "The ./pants script will detect any changes the next time you run it.")
    yield "\nYou are now ready to use Pants!"
