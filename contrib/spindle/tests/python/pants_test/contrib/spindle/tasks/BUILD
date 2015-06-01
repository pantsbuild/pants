# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'tasks',
  dependencies = [
    ':spindle_gen',
  ],
)

python_tests(
  name = 'spindle_gen',
  sources = ['test_spindle_gen.py'],
  dependencies = [
    '3rdparty/python:mock',
    'contrib/spindle/src/python/pants/contrib/spindle/tasks:spindle_gen',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)
