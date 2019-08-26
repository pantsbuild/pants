# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py', 'bootstrap_pants_pex.py'],
  dependencies = [
    'src/python/pants/goal:task_registrar',
    'src/python/pants/task',
  ]
)
