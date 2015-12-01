# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'what_changed',
  sources = ['test_what_changed.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/targets:python',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/build_graph',
    'src/python/pants/core_tasks',
    'src/python/pants/goal:workspace',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)
