# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'jvm_tool_task_test_base',
  sources = ['jvm_tool_task_test_base.py'],
  dependencies = [
    pants('src/python/pants/backend/jvm/tasks:bootstrap_jvm_tools'),
    pants('src/python/pants/base:dev_backend_loader'),
    pants('src/python/pants/util:dirutil'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_library(
  name = 'nailgun_task_test_base',
  sources = ['nailgun_task_test_base.py'],
  dependencies = [
    pants(':jvm_tool_task_test_base'),
    pants('src/python/pants/backend/jvm/tasks:nailgun_task'),
  ]
)

python_library(
  name = 'jar_task_test_base',
  sources = ['jar_task_test_base.py'],
  dependencies = [
    pants(':nailgun_task_test_base'),
  ]
)
