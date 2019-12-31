# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  sources=['test_findbugs.py'],
  dependencies=[
    'contrib/findbugs/src/python/pants/contrib/findbugs/tasks',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='integration',
  sources=['test_findbugs_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'contrib/findbugs:java_tests_directory',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=520,
)
