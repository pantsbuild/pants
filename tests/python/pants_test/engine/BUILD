# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'engine_test_base',
  sources = ['base_engine_test.py'],
  dependencies = [
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'test_engine',
  sources = ['test_engine.py'],
  dependencies = [
    ':engine_test_base',
    'src/python/pants/base:exceptions',
    'src/python/pants/engine',
  ],
)

python_tests(
  name = 'test_round_engine',
  sources = ['test_round_engine.py'],
  dependencies = [
    ':engine_test_base',
    'src/python/pants/engine',
    'src/python/pants/task',
    'tests/python/pants_test:base_test',
  ],
)
