# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['register.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:workunit',
    'src/python/pants/goal:task_registrar',
  ],
  tags = {'partially_type_checked'},
)

