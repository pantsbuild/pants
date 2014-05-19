# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'bootstrap_jvm_tools',
  sources = ['bootstrap_jvm_tools.py'],
  dependencies = [
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/jvm:ivy_task_mixin'),
    pants('src/python/pants/tasks:task'),
  ],
)


python_library(
  name = 'ivy_resolve',
  sources = ['ivy_resolve.py'],
  dependencies = [
    pants(':ivy_utils'),
    pants(':nailgun_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/base:cache_manager'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/jvm:ivy_task_mixin'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
  ],
)


python_library(
  name = 'ivy_task_mixin',
  sources = ['ivy_task_mixin.py'],
  dependencies = [
    pants(':ivy_utils'),
    pants('src/python/pants/base:cache_manager'),
    pants('src/python/pants/ivy'),
  ],
)


python_library(
  name = 'ivy_utils',
  sources = ['ivy_utils.py'],
  resources = globs('templates/ivy_resolve/*.mustache'),
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:generator'),
    pants('src/python/pants/base:revision'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/java:util'),
  ],
)


python_library(
  name = 'jvm_tool_bootstrapper',
  sources = ['jvm_tool_bootstrapper.py'],
  dependencies = [
    pants(':jvm_tool_bootstrapper'),
    pants('src/python/pants/base:exceptions'),
  ],
)

python_library(
  name = 'jvm_tool_task_mixin',
  sources = ['jvm_tool_task_mixin.py'],
  dependencies = [],
)


python_library(
  name = 'nailgun_task',
  sources = ['nailgun_task.py'],
  dependencies = [
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/java:executor'),
    pants('src/python/pants/java:nailgun_executor'),
    pants('src/python/pants/java:distribution'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/jvm:jvm_tool_task_mixin'),
    pants('src/python/pants/tasks:task'),
    pants('src/python/pants/tasks:console_task'),
  ],
)