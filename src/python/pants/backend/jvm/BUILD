# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    pants('src/python/pants/backend/core/tasks:group_task'),
    pants('src/python/pants/backend/jvm/targets:all'),
    pants('src/python/pants/backend/jvm/tasks:all'),
    pants('src/python/pants/base:build_file_aliases'),
    pants(':ivy_utils'),
    pants(':jvm_tool_bootstrapper'),
  ],
)

python_library(
  name = 'ivy_utils',
  sources = ['ivy_utils.py'],
  resources = globs('tasks/templates/ivy_resolve/*.mustache'),
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:generator'),
    pants('src/python/pants/base:revision'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/util:dirutil'),
  ],
)


python_library(
  name = 'jvm_tool_bootstrapper',
  sources = ['jvm_tool_bootstrapper.py'],
  dependencies = [
    pants('src/python/pants/base:exceptions'),
  ],
)

