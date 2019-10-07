# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import subprocess

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.task.task import Task

from pants.contrib.buildrefactor.buildozer_binary import BuildozerBinary


logger = logging.getLogger(__name__)


class Buildozer(Task):
    """Enables interaction with the Buildozer Go binary

  Behavior:
  1. `./pants buildozer --add-dependencies=<dependencies>`
      will add the dependency to the context's relative BUILD file.

      Example: `./pants buildozer --add-dependencies='a/b b/c' //tmp:tmp`

  2. `./pants buildozer --remove-dependencies=<dependencies>`
      will remove the dependency from the context's BUILD file.

      Example: `./pants buildozer --remove-dependencies='a/b b/c' //tmp:tmp`

    Note that buildozer assumes that BUILD files contain a name field for the target.
  """

    options_scope = "buildozer"

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (BuildozerBinary.scoped(cls),)

    @classmethod
    def register_options(cls, register):
        register("--add-dependencies", type=str, help="The dependency or dependencies to add")
        register("--remove-dependencies", type=str, help="The dependency or dependencies to remove")
        register("--command", type=str, help="A custom buildozer command to execute")

    def execute(self):
        options = self.get_options()
        if options.command:
            if options.add_dependencies or options.remove_dependencies:
                raise TaskError(
                    "Buildozer custom command cannot be used together with "
                    + "--add-dependencies or --remove-dependencies."
                )
            self._execute_buildozer_script(options.command)

        if options.add_dependencies:
            self._execute_buildozer_script("add dependencies {}".format(options.add_dependencies))

        if options.remove_dependencies:
            self._execute_buildozer_script(
                "remove dependencies {}".format(options.remove_dependencies)
            )

    def _execute_buildozer_script(self, command):
        binary = BuildozerBinary.scoped_instance(self)
        for root in self.context.target_roots:
            binary.execute(command, root.address.spec, context=self.context)

    @classmethod
    def _execute_buildozer_command(cls, buildozer_command):
        try:
            subprocess.check_call(buildozer_command, cwd=get_buildroot())
        except subprocess.CalledProcessError as err:
            if err.returncode == 3:
                logger.warning("{} ... no changes were made".format(buildozer_command))
            else:
                raise TaskError(
                    "{} ... exited non-zero ({}).".format(buildozer_command, err.returncode)
                )
