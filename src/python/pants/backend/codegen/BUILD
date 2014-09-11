# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'src/python/pants/backend/codegen/tasks:all',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/targets:python',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/goal:task_registrar',
  ]
)
