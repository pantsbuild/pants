# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'tasks',
  dependencies = [
    ':spindle_gen',
  ],
)

python_library(
  name = 'spindle_gen',
  sources = ['spindle_gen.py'],
  dependencies = [
    '3rdparty/python:twitter.common.dirutil',
    'contrib/spindle/src/python/pants/contrib/spindle/targets',
    'contrib/spindle/src/python/pants/contrib/spindle/targets:spindle_thrift_library',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
  ],
)
