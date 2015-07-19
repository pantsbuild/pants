# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'tasks',
  dependencies = [
    'contrib/scalajs/src/python/pants/contrib/scalajs/targets',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/backend/jvm/tasks/jvm_compile:scala',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
  ],
  sources = globs('*.py'),
)
