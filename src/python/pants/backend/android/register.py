# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.android.tasks.aapt_gen import AaptGen
from pants.backend.android.tasks.dx_compile import DxCompile
from pants.base.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases.create(
    targets={
      'android_binary': AndroidBinary,
      'android_resources': AndroidResources,
    }
  )

def register_goals():
  task(name='aapt', action=AaptGen).install('gen')

  task(name='dex', action=DxCompile,
       dependencies=['compile']).install('dex')
