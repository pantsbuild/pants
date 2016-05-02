# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:checkstyle',
    'src/python/pants/backend/jvm/tasks:scalastyle',
    'src/python/pants/goal:task_registrar',
  ],
)

