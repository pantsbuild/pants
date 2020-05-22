# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='sitegen',
  dependencies=[
    'pants-plugins/3rdparty/python:beautifulsoup4',
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
    'src/python/pants/backend/docgen/tasks'
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  dependencies=[
    ':sitegen',
    'pants-plugins/3rdparty/python:beautifulsoup4',
    'src/python/pants/engine/internals:native',
  ],
  tags = {"partially_type_checked"},
)
