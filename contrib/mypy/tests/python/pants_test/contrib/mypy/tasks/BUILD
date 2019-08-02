# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='mypy_integration',
  sources=['test_mypy_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
    'tests/python/pants_test:interpreter_selection_utils',
  ],
  tags={'integration'},
)

python_tests(
  name='mypy',
  source = 'test_mypy.py',
  dependencies=[
    'tests/python/pants_test:task_test_base',
    'contrib/mypy/src/python/pants/contrib/mypy/tasks',
  ],
)
