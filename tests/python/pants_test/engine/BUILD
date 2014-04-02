# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'engine_test_base',
  sources = ['base_engine_test.py'],
  dependencies = [
    pants('src/python/pants/goal'),
  ]
)

python_test_suite(
  name = 'engine',
  dependencies = [
    pants(':test_engine'),
    pants(':test_group_engine'),
  ]
)

python_tests(
  name = 'test_engine',
  sources = ['test_engine.py'],
  dependencies = [
    pants(':engine_test_base'),
    pants('3rdparty/python:mox'),
    pants('src/python/pants/engine'),
    pants('src/python/pants/tasks:task_error'),
    pants('tests/python/pants_test:base-test'),
  ],
)

python_tests(
  name = 'test_group_engine',
  sources = ['test_group_engine.py'],
  dependencies = [
    pants(':engine_test_base'),
    pants('src/python/pants/engine'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/tasks:check_exclusives'),
    pants('src/python/pants/tasks:common'),
    pants('tests/python/pants_test/base:base-test'),
    pants('tests/python/pants_test:base-test'),
  ],
)
