# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='all',
  dependencies=[
    ':sitegen',
  ],
)

python_library(
  name='sitegen',
  sources=['sitegen.py'],
  dependencies = [
    '3rdparty/python:pystache',
    '3rdparty/python:six',
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
  ],
)
