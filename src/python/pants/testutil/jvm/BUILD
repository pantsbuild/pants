# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='jvm_tool_task_test_base',
  sources=['jvm_tool_task_test_base.py'],
  dependencies=[
    '//:build_tools',
    '//:3rdparty_directory',
    ':jvm_task_test_base',
    'src/python/pants/backend/jvm/subsystems:jvm_tool_mixin',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:bootstrap_jvm_tools',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/build_graph',
    'src/python/pants/core/util_rules',
    'src/python/pants/ivy',
    'src/python/pants/java/jar',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='nailgun_task_test_base',
  sources=['nailgun_task_test_base.py'],
  dependencies=[
    ':jvm_tool_task_test_base',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='jar_task_test_base',
  sources=['jar_task_test_base.py'],
  dependencies=[
    ':nailgun_task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='jvm_task_test_base',
  sources=['jvm_task_test_base.py'],
  dependencies=[
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)
