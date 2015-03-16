# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'artifact',
  sources = ['artifact.py'],
  dependencies = [
    '3rdparty/python:six',
    ':repository',
    'src/python/pants/base:payload_field',
  ],
)

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    ':artifact',
    ':repository',
    'src/python/pants/backend/core/tasks:group_task',
    'src/python/pants/backend/jvm/targets:all',
    'src/python/pants/backend/jvm/tasks:all',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
  ],
)

python_library(
  name = 'ivy_utils',
  sources = ['ivy_utils.py'],
  resources = globs('tasks/templates/ivy_resolve/*.mustache'),
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:revision',
    'src/python/pants/base:target',
    'src/python/pants/ivy',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'repository',
  sources = ['repository.py'],
)
