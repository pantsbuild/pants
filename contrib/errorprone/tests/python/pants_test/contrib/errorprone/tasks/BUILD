# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=['test_errorprone.py'],
  dependencies=[
    'contrib/errorprone/src/python/pants/contrib/errorprone/tasks',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='integration',
  sources=['test_errorprone_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/errorprone:java_tests_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=420,
)
