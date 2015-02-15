# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.android.tasks.aapt_builder import AaptBuilder
from pants.backend.android.tasks.aapt_gen import AaptGen
from pants.backend.android.tasks.dx_compile import DxCompile
from pants.backend.android.tasks.sign_apk import SignApkTask
from pants.backend.android.tasks.zipalign import Zipalign
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
  task(name='dex', action=DxCompile).install('binary')
  task(name='apk', action=AaptBuilder).install()
  task(name='sign', action=SignApkTask).install()
  task(name='zipalign', action=Zipalign).install('bundle')
