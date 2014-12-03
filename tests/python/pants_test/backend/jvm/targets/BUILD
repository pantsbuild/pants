# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
    'tests/python/pants_test:base_test',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:target',
    'src/python/pants/backend/jvm/targets:jvm',
  ],
)
