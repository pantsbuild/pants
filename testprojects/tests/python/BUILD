# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':example_test_directory',
    'testprojects/tests/python/pants:all_directories',
  ],
)

files(
  name = 'example_test_directory',
  sources = ['example_test/**/*'],
  dependencies = [
    'testprojects/src/python:python_distribution_directory',
  ],
)

files(
  name = 'owners_integration_target',
  sources = ['pants/BUILD'],
  dependencies = [
    'testprojects/tests/python/pants:dummies_directory',
  ],
)
