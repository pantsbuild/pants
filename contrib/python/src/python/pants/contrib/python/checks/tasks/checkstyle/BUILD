# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='all',
  sources=rglobs('*.py'),
  dependencies = [
    '3rdparty/python:pep8',
    '3rdparty/python:pyflakes',
    '3rdparty/python:six',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/util:meta',
  ],
)
