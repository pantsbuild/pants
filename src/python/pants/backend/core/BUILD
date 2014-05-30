# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'src/python/pants/backend/core/targets:all',
    'src/python/pants/backend/core/tasks:all',
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
  ]
)
