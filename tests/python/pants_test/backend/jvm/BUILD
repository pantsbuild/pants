# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'jvm',
  dependencies = [
    ':jvm_debug_config',
    'tests/python/pants_test/backend/jvm/targets',
    'tests/python/pants_test/backend/jvm/tasks',
  ]
)

python_tests(
  name = 'jvm_debug_config',
  sources = ['test_jvm_debug_config.py'],
  dependencies = [
    'src/python/pants/backend/jvm:jvm_debug_config',
    'tests/python/pants_test/base:context_utils',
  ]
)
