# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

from pants.base.build_environment import get_default_pants_config_file
from pants.base.exceptions import TaskError
from pants.task.console_task import ConsoleTask
from pants.version import VERSION as pants_version


class GeneratePantsIni(ConsoleTask):
  """Generate pants.ini with sensible defaults."""

  def console_output(self, _targets):
    pants_ini_path = Path(get_default_pants_config_file())
    pants_ini_content = dedent(f"""\
      [GLOBAL]
      pants_version: {pants_version}
      """
    )

    if pants_ini_path.exists():
      raise TaskError(
        f"{pants_ini_path} already exists. To update config values, please directly modify "
        f"pants.ini. For example, you may want to add these entries:\n\n{pants_ini_content}"
      )

    yield dedent(f"""\
      Adding sensible defaults to {pants_ini_path}:
      * Pinning `pants_version` to `{pants_version}`.
      """
    )

    pants_ini_path.write_text(pants_ini_content)

    yield ("You may modify these values directly in the file at any time. "
           "The ./pants script will detect any changes the next time you run it.")
    yield "\nYou are now ready to use Pants!"
