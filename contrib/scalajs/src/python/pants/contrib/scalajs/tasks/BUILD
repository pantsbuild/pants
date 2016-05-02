# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'tasks',
  dependencies = [
    'contrib/scalajs/src/python/pants/contrib/scalajs/subsystems',
    'contrib/scalajs/src/python/pants/contrib/scalajs/targets',
    'src/python/pants/backend/jvm/tasks/jvm_compile:zinc',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/goal:products',
    'src/python/pants/util:memo',
  ],
  sources = globs('*.py'),
)
