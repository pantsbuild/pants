# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    ':resources',
    '3rdparty/python:pex',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks2',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:workunit',
    'src/python/pants/util:dirutil',
  ]
)

resources(
  name='resources',
  sources=globs('templates/python_eval/*.mustache'),
)
