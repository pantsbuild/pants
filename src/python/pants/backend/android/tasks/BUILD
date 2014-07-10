# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


dependencies(
  name = 'common',
  dependencies = [
    'src/python/pants/backend/core/tasks:common',
  ],
)

python_library(
  name = 'all',
  dependencies = [
    ':common',
    ':android_task',
    ':aapt_gen',
  ],
)

python_library(
  name = 'android_task',
  sources = ['android_task.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/backend/android:android_distribution'),
  ],
)

python_library(
  name = 'aapt_gen',
  sources = ['aapt_gen.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants(':common'),
    pants('src/python/pants/backend/android/targets:android'),
    pants('src/python/pants/backend/android/tasks:android_task'),
    pants('src/python/pants/backend/codegen/tasks:code_gen'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/base:address'),
  ],
)