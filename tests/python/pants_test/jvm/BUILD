# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'jvm_tool_task_test_base',
  sources = ['jvm_tool_task_test_base.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/codegen/targets:python'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/backend/jvm/tasks:bootstrap_jvm_tools'),
    pants('src/python/pants/backend/jvm/tasks:bootstrap_jvm_tools'),
    pants('src/python/pants/backend/python/targets:python'),
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
