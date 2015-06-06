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
    'contrib/spindle/src/python/pants/contrib/spindle/targets:spindle_thrift_library',
    'contrib/spindle/src/python/pants/contrib/spindle/tasks:spindle_gen',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:build_file_aliases',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ],
)
