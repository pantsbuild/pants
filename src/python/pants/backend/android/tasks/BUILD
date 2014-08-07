# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':android_task',
    ':aapt_gen',
    ':aapt_task',
    ':dx_compile',
  ],
)

python_library(
  name = 'android_task',
  sources = ['android_task.py'],
  dependencies = [
    pants('src/python/pants/backend/core/tasks:common'),
    pants('src/python/pants/backend/android:android_distribution'),
  ],
)

python_library(
  name = 'aapt_task',
  sources = ['android_task.py'],
  dependencies = [
    pants('src/python/pants/backend/android/tasks:android_task'),
  ],
)

python_library(
  name = 'aapt_gen',
  sources = ['aapt_gen.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('src/python/pants/backend/android/targets:android'),
    pants('src/python/pants/backend/android/tasks:android_task'),
    pants('src/python/pants/backend/codegen/tasks:code_gen'),
    pants('src/python/pants/backend/core/tasks:common'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:exceptions'),
  ],
)

python_library(
  name = 'dx_compile',
  sources = ['dx_compile.py'],
  dependencies = [
    pants('src/python/pants/backend/android/targets:android'),
    pants('src/python/pants/backend/android/tasks:android_task'),
    pants('src/python/pants/backend/core/tasks:common'),
    pants('src/python/pants/backend/jvm/tasks:nailgun_task'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/util:dirutil'),
  ],
)