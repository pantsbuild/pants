# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='artifact',
  sources=['test_artifact.py'],
  dependencies=[
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm:repository',
    'tests/python/pants_test:test_base',
  ]
)

python_tests(
  name='test_safeargs',
  sources=['test_safeargs.py'],
  dependencies=[
    'src/python/pants/backend/jvm:argfile'
  ]
)

python_library(
  name='jvm_tool_task_test_base',
  sources=['jvm_tool_task_test_base.py'],
  dependencies=[
    'src/python/pants/testinfra/jvm:jvm_tool_task_test_base',
  ]
)

python_library(
  name='nailgun_task_test_base',
  sources=['nailgun_task_test_base.py'],
  dependencies=[
    'src/python/pants/testinfra/jvm:nailgun_task_test_base',
  ]
)

python_library(
  name='jar_task_test_base',
  sources=['jar_task_test_base.py'],
  dependencies=[
    'src/python/pants/testinfra/jvm:jar_task_test_base',
  ]
)

python_library(
  name='jvm_task_test_base',
  sources=['jvm_task_test_base.py'],
  dependencies=[
    'src/python/pants/testinfra/jvm:jvm_task_test_base',
  ]
)
