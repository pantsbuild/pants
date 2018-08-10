# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='all',
  sources=rglobs('*.py'),
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python:pycodestyle',
    '3rdparty/python:pyflakes',
    '3rdparty/python:pex',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:exceptions',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/task',
    'src/python/pants/util:meta',
  ]
)
