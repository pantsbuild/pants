# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='tasks2',
  sources=globs('*.py'),
  dependencies=[
    '3rdparty/python:pex',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:python_setup',
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:fingerprint_strategy',
    'src/python/pants/invalidation',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ]
)
