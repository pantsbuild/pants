# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_test_suite(
  name = 'targets',
  dependencies = [
    ':unpacked_jars',
  ]
)

python_tests(
  name = 'unpacked_jars',
  sources = ['test_unpacked_jars.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'tests/python/pants_test:base_test',
  ]
)
