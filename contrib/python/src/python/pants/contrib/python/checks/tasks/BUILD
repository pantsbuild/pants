# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:pex',
    ':resources',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:workunit',
    'src/python/pants/python',
    'src/python/pants/task',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
  tags = {'partially_type_checked'},
)

resources(
  name='resources',
  sources=['templates/python_eval/*.mustache'],
)
