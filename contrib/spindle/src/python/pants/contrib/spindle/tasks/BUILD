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
    'contrib/spindle/src/python/pants/contrib/spindle/targets',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/option',
    'src/python/pants/util:dirutil',
  ],
)
