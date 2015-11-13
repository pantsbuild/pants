# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='all',
  sources=rglobs('*.py'),
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:coverage',
    '3rdparty/python:pex',
    '3rdparty/python:pytest',
    '3rdparty/python:pytest-cov',
    '3rdparty/python:six',
    '3rdparty/python:pep8',
    '3rdparty/python:pyflakes',
    'src/python/pants/backend/codegen/targets:python',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/build_graph',
  ]
)
