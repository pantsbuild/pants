# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['register.py'],
  dependencies = [
    'src/python/pants/backend/core/tasks:all',
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
    'src/python/pants/base:deprecated',
    'src/python/pants/source',
  ],
)

python_library(
  name = 'core',
  sources = [
    'from_target.py',
  ],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/build_graph',
  ]
)
