# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='lib',
  dependencies = [
    '3rdparty/python:future',
    'contrib/python/src/python/pants/contrib/python/checks/checker',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/option/util',
  ],
)

python_tests(
  dependencies=[
    '3rdparty/python:future',
    ':lib',
    'contrib/python/src/python/pants/contrib/python/checks/checker',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test:test_base',
  ]
)
