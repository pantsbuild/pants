# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'src/python/pants/backend/project_info/tasks:dependencies',
    'src/python/pants/backend/project_info/tasks:depmap',
    'src/python/pants/backend/project_info/tasks:eclipse_gen',
    'src/python/pants/backend/project_info/tasks:ensime_gen',
    'src/python/pants/backend/project_info/tasks:export',
    'src/python/pants/backend/project_info/tasks:filedeps',
    'src/python/pants/backend/project_info/tasks:idea_gen',
    'src/python/pants/goal:task_registrar',
  ],
)

