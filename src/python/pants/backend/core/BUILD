# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['register.py'],
  dependencies = [
    'src/python/pants/backend/core/targets:all',
    'src/python/pants/backend/core/tasks:all',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:source_root',
    'src/python/pants/goal:task_registrar',
    ':core',
  ]
)

python_library(
  name = 'core',
  sources = [
    'from_target.py',
    'wrapped_globs.py',
  ],
  dependencies = [
    '3rdparty/python:six',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/backend/core/targets:all',
    'src/python/pants/backend/core/tasks:all',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/fs',
    'src/python/pants/util:dirutil',
  ]
)
