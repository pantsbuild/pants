# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'pants-plugins/src/python/internal_backend/sitegen/tasks:all',
    'pants-plugins/src/python/internal_backend/sitegen/tasks:sitegen',
    'src/python/pants/goal:task_registrar',
  ],
)
