# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'src/python/pants/backend/core/targets:all',
    'src/python/pants/backend/core/tasks:all',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/commands:goal',
    ':core',
  ]
)

python_library(
  name = 'core',
  sources = ['wrapped_globs.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/backend/core/targets:all',
    'src/python/pants/backend/core/tasks:all',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
  ]
)
