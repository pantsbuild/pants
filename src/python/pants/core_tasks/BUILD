# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='core_tasks',
  sources=globs('*.py'),
  resource_targets=[':templates',],
  dependencies=[
    '3rdparty/python:ansicolors',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/help',
    'src/python/pants/option',
    'src/python/pants/pantsd/subsystem:pants_daemon_launcher',
    'src/python/pants/reporting',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ])

resources(
  name = 'templates',
  sources = globs('templates/**/*.mustache'),
)
