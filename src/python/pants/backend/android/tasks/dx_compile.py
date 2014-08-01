# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.targets.android_dex import AndroidDex
from pants.backend.android.tasks.android_task import AndroidTask
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir

class DxCompile(AndroidTask, NailgunTask):
  """
  Compile java classes into dex files, Dalvik executables.
  """
  _CONFIG_SECTION = 'dx-tool'

  # @classmethod
  # def setup_parser(cls, option_group, args, mkflag):
  #   # VM options go here
  #   pass

  def __init__(self, context, workdir):
    print("WE ARE AT DX_COMPILE")
    super(DxCompile, self).__init__(context, workdir)
    self._android_dist = self.android_sdk


  def is_dextarget(self):
    return isinstance(AndroidDex)

  @property
  def config_section(self):
    return self._CONFIG_SECTION


  def execute(self):
    safe_mkdir(self.workdir)

    # with self.context.new_workunit(name='dex_compile', labels=[WorkUnit.MULTITOOL]):  #Which code?
    #   for target in self.context.targets(predicate=self.is_gentarget):
    #     pass
    #TODO check for empty class files there is no valid empty dex file.