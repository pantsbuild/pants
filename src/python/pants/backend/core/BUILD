# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['register.py'],
  dependencies = [
    'src/python/pants/backend/core/targets:doc',
    'src/python/pants/backend/core/tasks:all',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:source_root',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
    ':core',
  ]
)

python_library(
  name = 'wrapped_globs',
  sources = [
    'wrapped_globs.py',
  ],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:six',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_manual',
    'src/python/pants/util:memo',
  ],
)

python_library(
  name = 'core',
  sources = [
    'from_target.py',
  ],
  dependencies = [
    '3rdparty/python:six',
    'src/python/pants/backend/core/tasks:all',
    'src/python/pants/base:build_environment',
    'src/python/pants/build_graph',
    'src/python/pants/util:dirutil',
    ':wrapped_globs',
  ]
)
