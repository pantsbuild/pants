# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.tasks.android_task import AndroidTask
from pants.backend.android.distribution.android_distribution import AndroidDistribution
from pants.backend.jvm.tasks.nailgun_task import NailgunTask


class DxCompile(NailgunTask, AndroidTask):
  """
  Compile java classes into dex files, Dalvik executables.
  """
  _CONFIG_SECTION = 'dx-tool'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    # VM options go here
    pass


  def init(self):
    pass

  @property
  def config_section(self):
    return self._CONFIG_SECTION



    #TODO check for empty class files there is no valid empty dex file.