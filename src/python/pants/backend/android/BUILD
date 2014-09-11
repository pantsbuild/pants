# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:all',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/goal:task_registrar',
  ]
)

python_library(
  name = 'android_distribution',
  sources = globs('distribution/*.py'),
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.log',
  ]
)
