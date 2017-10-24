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
  1. `./pants buildozer --add-dependencies=<dependencies>`
      will add the dependency to the context's relative BUILD file.

      Example: `./pants buildozer --add-dependencies='a/b b/c' //tmp:tmp`

  2. `./pants buildozer --remove-dependencies=<dependencies>`
      will remove the dependency from the context's BUILD file.

      Example: `./pants buildozer --remove-dependencies='a/b b/c' //tmp:tmp`

    Note that buildozer assumes that BUILD files contain a name field for the target.
  """

  @classmethod
  def subsystem_dependencies(cls):
    return super(Buildozer, cls).subsystem_dependencies() + (BinaryUtil.Factory,)

  @classmethod
  def register_options(cls, register):
    register('--version', default='0.4.5', help='Version of buildozer.')
    register('--add-dependencies', type=str, help='The dependency or dependencies to add')
    register('--remove-dependencies', type=str, help='The dependency or dependencies to remove')
    register('--command', type=str, help='A custom buildozer command to execute')

  def __init__(self, *args, **kwargs):
    super(Buildozer, self).__init__(*args, **kwargs)

    self.options = self.get_options()
    self._executable = BinaryUtil.Factory.create().select_binary('scripts/buildozer', self.options.version, 'buildozer')

  def execute(self):
    if self.options.command:
      if self.options.add_dependencies or self.options.remove_dependencies:
        raise TaskError('Buildozer custom command cannot be used together with ' +
                        '--add-dependencies or --remove-dependencies.')
      self._execute_buildozer_script(self.options.command)

    if self.options.add_dependencies:
      self._execute_buildozer_script('add dependencies {}'.format(self.options.add_dependencies))

    if self.options.remove_dependencies:
      self._execute_buildozer_script('remove dependencies {}'.format(self.options.remove_dependencies))

  def _execute_buildozer_script(self, command):
    for root in self.context.target_roots:
      address = root.address
      buildozer_command = [self._executable, command, '//{}:{}'.format(address._spec_path, address._target_name)]

      try:
        subprocess.check_call(buildozer_command, cwd=get_buildroot())
      except subprocess.CalledProcessError as err:
        if (err.returncode == 3):
          raise TaskError('{} ... no changes were made'.format(buildozer_command))
        else:
          raise TaskError('{} ... exited non-zero ({}).'.format(buildozer_command, err.returncode))
