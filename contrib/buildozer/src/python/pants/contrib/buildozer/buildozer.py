# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.binaries.binary_util import BinaryUtil
from pants.task.task import Task
from pants.util.process_handler import subprocess


class Buildozer(Task):
  """Enables interaction with the Buildozer Go binary

  Behavior:
  1. `./pants buildozer --add-dependencies=<dependencies> --location=<directory>`
      will add the dependency to the location's relative BUILD file.

      Example: `./pants buildozer --add-dependencies='a/b b/c' //tmp:tmp`

  2. `./pants buildozer --remove-dependencies=<dependencies> --location=<directory>`
      will remove the dependency from the location's relative BUILD file.

      Example: `./pants buildozer --remove-dependencies='a/b b/c' //tmp:tmp`

  Note that buildozer assumes that BUILD files contain a name field for the target.
  """

  @classmethod
  def register_options(cls, register):
    register('--version', default='0.4.5', help='Version of buildozer.')
    register('--add-dependencies', type=str, help='The dependency or dependencies to add')
    register('--remove-dependencies', type=str, help='The dependency or dependencies to remove')

  def __init__(self, *args, **kwargs):
    super(Buildozer, self).__init__(*args, **kwargs)

    self.options = self.get_options()
    self.address = self.context.target_roots[0].address
    self._executable = BinaryUtil.Factory.create().select_binary('scripts/buildozer', self.options.version, 'buildozer')

  def execute(self):
    if self.options.add_dependencies:
      self.add_dependencies()

    if self.options.remove_dependencies:
      self.remove_dependencies()

  def add_dependencies(self):
    self._execute_buildozer_script('add dependencies {}'.format(self.options.add_dependencies))

  def remove_dependencies(self):
    self._execute_buildozer_script('remove dependencies {}'.format(self.options.remove_dependencies))

  def _execute_buildozer_script(self, command):
    buildozer_command = [self._executable, command, '//{}:{}'.format(self.address._spec_path, self.address._target_name)]

    try:
      subprocess.check_call(buildozer_command, cwd=get_buildroot())
    except subprocess.CalledProcessError as err:
      if (err.returncode == 3):
        raise TaskError('{} ... no changes were made'.format(buildozer_command))
      else:
        raise TaskError('{} ... exited non-zero ({}).'.format(buildozer_command, err.returncode))
