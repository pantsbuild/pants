# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    ':pants_requirement',
    ':python_artifact',
    ':python_requirements',
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/python',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'all_utils',
  sources = ['*.py', '!__init__.py', '!register.py'],
  dependencies = [
    ':interpreter_cache',
    ':python_artifact',
    ':python_requirements',
    'src/python/pants/python',
  ],
  tags = {"partially_type_checked"},
)

page(
  name = 'readme',
  source = 'README.md',
  links = [
    'src/python/pants:readme',
  ]
)

python_library(
  name = 'interpreter_cache',
  sources = ['interpreter_cache.py'],
  dependencies = [
    '3rdparty/python:pex',
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:exceptions',
    'src/python/pants/process',
    'src/python/pants/python',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'pants_requirement',
  sources = ['pants_requirement.py'],
  dependencies = [
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/python',
    'src/python/pants/util:meta',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'python_artifact',
  sources = ['python_artifact.py'],
  dependencies = [
    'src/python/pants/base:payload_field',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'python_requirement',
  sources = ['python_requirement.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/python'
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'python_requirements',
  sources = ['python_requirements.py'],
  tags = {"partially_type_checked"},
)

