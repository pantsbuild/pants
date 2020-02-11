# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='python_eval',
  sources=['test_python_eval.py'],
  dependencies=[
    'src/python/pants/python',
    'contrib/python/src/python/pants/contrib/python/checks/tasks',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
  ],
  tags = {'partially_type_checked'},
)
