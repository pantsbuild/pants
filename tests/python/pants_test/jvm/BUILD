# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='artifact',
  sources=['test_artifact.py'],
  dependencies = [
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm:repository',
    'tests/python/pants_test:base_test',
  ],
)

python_library(
  name='jvm_tool_task_test_base',
  sources=['jvm_tool_task_test_base.py'],
  dependencies = [
    ':jvm_task_test_base',
    'src/python/pants/backend/jvm/subsystems:jvm_tool_mixin',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:bootstrap_jvm_tools',
    'src/python/pants/base:build_environment',
    'src/python/pants/build_graph',
    'src/python/pants/ivy',
  ],
)

python_library(
  name='nailgun_task_test_base',
  sources=['nailgun_task_test_base.py'],
  dependencies = [
    ':jvm_tool_task_test_base',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
  ],
)

python_library(
  name='jar_task_test_base',
  sources=['jar_task_test_base.py'],
  dependencies = [
    ':nailgun_task_test_base',
  ],
)

python_library(
  name='jvm_task_test_base',
  sources=['jvm_task_test_base.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)
