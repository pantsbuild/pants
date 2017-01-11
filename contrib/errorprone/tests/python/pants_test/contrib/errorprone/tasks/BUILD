# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=['test_errorprone.py'],
  dependencies=[
    'contrib/errorprone/src/python/pants/contrib/errorprone/tasks',
    'tests/python/pants_test/jvm:nailgun_task_test_base',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='integration',
  sources=['test_errorprone_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
  timeout=300,
)
