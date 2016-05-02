# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='python',
  sources=globs('*.py'),
  resource_targets=[
    ':resources'
  ],
  dependencies = [
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:workunit',
  ],
)

resources(
  name='resources',
  sources=globs('templates/python_eval/*.mustache'),
)
