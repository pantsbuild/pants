# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.android.targets.android_binary import AndroidBinary
from pants.contrib.android.targets.android_dependency import AndroidDependency
from pants.contrib.android.targets.android_library import AndroidLibrary
from pants.contrib.android.targets.android_resources import AndroidResources
from pants.contrib.android.tasks.aapt_builder import AaptBuilder
from pants.contrib.android.tasks.aapt_gen import AaptGen
from pants.contrib.android.tasks.dx_compile import DxCompile
from pants.contrib.android.tasks.sign_apk import SignApkTask
from pants.contrib.android.tasks.unpack_libraries import UnpackLibraries
from pants.contrib.android.tasks.zipalign import Zipalign


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'android_binary': AndroidBinary,
      'android_dependency': AndroidDependency,
      'android_library': AndroidLibrary,
      'android_resources': AndroidResources,
    }
  )


def register_goals():
  task(name='unpack-libs', action=UnpackLibraries).install('unpack-jars')
  task(name='aapt', action=AaptGen).install('gen')
  task(name='dex', action=DxCompile).install('binary')
  task(name='apk', action=AaptBuilder).install()
  task(name='sign', action=SignApkTask).install()
  task(name='zipalign', action=Zipalign).install('bundle')
