# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='jvm_compile',
  dependencies=[
    ':jvm_fingerprint_strategy',
  ],
)

python_tests(
  name = 'jvm_fingerprint_strategy',
  sources = ['test_jvm_fingerprint_strategy.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks/jvm_compile:jvm_fingerprint_strategy',
    'tests/python/pants_test:base_test',
  ]
)
