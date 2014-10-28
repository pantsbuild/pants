# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base',
  dependencies = [
    'tests/python/pants_test:base_test',
  ],
)

python_test_suite(
  name = 'targets',
  dependencies = [
    ':jvm_target',
  ]
)

python_tests(
  name = 'jvm_target',
  sources = ['test_jvm_target.py'],
  dependencies = [
    ':base',
    'src/python/pants/base:target',
    'src/python/pants/backend/jvm/targets:jvm',
    ],
)
