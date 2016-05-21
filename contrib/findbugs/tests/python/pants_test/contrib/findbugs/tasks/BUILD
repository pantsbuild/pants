# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='tasks',
  sources=['test_findbugs.py'],
  dependencies=[
    'contrib/findbugs/src/python/pants/contrib/findbugs/tasks:tasks',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='integration',
  sources=['test_findbugs_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
  timeout=300,
)
