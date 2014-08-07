# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

dependencies(
  name='jvm_compile',
  dependencies=[
    pants(':jvm_fingerprint_strategy'),
  ],
)

python_tests(
  name = 'jvm_fingerprint_strategy',
  sources = ['test_jvm_fingerprint_strategy.py'],
  dependencies = [
    pants('src/python/pants/backend/jvm/tasks/jvm_compile:jvm_fingerprint_strategy'),
    pants('tests/python/pants_test:base_test'),
  ]
)
