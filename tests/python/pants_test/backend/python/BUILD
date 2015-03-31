# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='python',
  dependencies=[
    ':test_python_requirement_list',
    'tests/python/pants_test/backend/python/tasks'
  ]
)

python_tests(
  name='test_python_requirement_list',
  sources=['test_python_requirement_list.py'],
  dependencies=[
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_file_aliases',
    'tests/python/pants_test:base_test'
  ]
)
