# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['register.py'],
  dependencies = [
    'src/python/pants/backend/docgen/targets',
    'src/python/pants/backend/docgen/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
)
