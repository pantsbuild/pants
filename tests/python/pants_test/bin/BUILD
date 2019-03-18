# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources='test_loader.py',
  dependencies=[
    'src/python/pants/bin',
    '3rdparty/python:future',
    '3rdparty/python:mock',
  ],
)

python_tests(
  name='integration',
  sources='test_loader_integration.py',
  dependencies=[
    'src/python/pants/bin',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)
