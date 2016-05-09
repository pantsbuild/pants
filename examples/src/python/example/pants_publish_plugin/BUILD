# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='pants-publish-plugin',
  sources=globs('*.py'),
  dependencies = [
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:jar_task',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/util:dirutil',
  ],
)
