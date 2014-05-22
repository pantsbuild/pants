# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'jvm_tool_task_test_base',
  sources = ['jvm_tool_task_test_base.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/jvm:bootstrap_jvm_tools'),
    pants('tests/python/pants_test:base_test'),
  ]
)

python_library(
  name = 'nailgun_task_test_base',
  sources = ['nailgun_task_test_base.py'],
  dependencies = [
    pants('src/python/pants/jvm:nailgun_task'),
    pants(':jvm_tool_task_test_base'),
  ]
)

python_library(
  name = 'jar_task_test_base',
  sources = ['jar_task_test_base.py'],
  dependencies = [
    pants(':nailgun_task_test_base'),
  ]
)
