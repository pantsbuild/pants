# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'targets',
  dependencies = [
    pants(':java'),
  ],
)

python_tests(
  name = 'java',
  sources = ['test_java_library.py'],
  dependencies = [
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('tests/python/pants_test:base_test'),
  ],
)
