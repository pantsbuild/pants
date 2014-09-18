# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='python',
  dependencies=[
    ':test_builder',
  ]
)

python_tests(
  name='test_builder',
  sources=['test_test_builder.py'],
  dependencies=[
    '3rdparty/python:coverage',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:test_builder',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test'
  ]
)
