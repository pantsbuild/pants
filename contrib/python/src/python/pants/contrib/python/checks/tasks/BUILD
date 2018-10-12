# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python:pex',
    ':resources',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:workunit',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ]
)

resources(
  name='resources',
  sources=globs('templates/python_eval/*.mustache'),
)
