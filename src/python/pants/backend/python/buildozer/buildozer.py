# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.binaries.binary_util import BinaryUtil
from pants.task.task import Task


class Buildozer(Task):
  """Enables interaction with the Buildozer Go binary
  
  Behavior:
  1. `./pants buildozer --add=<dependency> --location=<directory>` 
      will add the dependency to the location's relative BUILD file.
  2. `./pants buildozer --remove=<dependency> --location=<directory>` 
      will remove the dependency from the location's relative BUILD file.

  Note that buildozer assumes that BUILD files contain a name field for the target.
  """

  @classmethod
  def register_options(cls, register):
    register('--version', advanced=True, fingerprint=True, default='0.4.5', help='Version of buildozer.')
    register('--add', type=str, advanced=True, default=None, help='The dependency to add')
    register('--remove', type=str, advanced=True, default=None, help='The dependency to remove')
    register('--location', type=str, advanced=True, default=None, help='The target location')

  def __init__(self, *args, **kwargs):
    super(Buildozer, self).__init__(*args, **kwargs)

    self.options = self.get_options()
    
  def execute(self):
    if self.options.add:
      self.add_dependency()

    if self.options.remove:
      self.remove_dependency()

  def add_dependency(self):
    self.execute_buildozer_script('add dependencies ' + self.options.add)
  
  def remove_dependency(self):
    self.execute_buildozer_script('remove dependencies ' + self.options.remove)

  def execute_buildozer_script(self, command):
    buildozer_command = [
      BinaryUtil.Factory.create().select_script('scripts/buildozer', self.options.version, 'buildozer'),
      command
    ]

    if self.options.get('location'):
      buildozer_command.append(self.options.location)

    try:
      subprocess.check_call(buildozer_command, cwd=get_buildroot())
    except subprocess.CalledProcessError as err:
      raise TaskError('{} ... exited non-zero ({}).'.format(buildozer_command, err.returncode))
