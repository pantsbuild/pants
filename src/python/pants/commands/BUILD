# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'command',
  sources = ['command.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_file',
    'src/python/pants/base:build_file_parser',
    'src/python/pants/base:target',
    'src/python/pants/base:build_graph',
  ]
)

python_library(
  name = 'pants_new',
  dependencies = [
    ':goal_runner',
  ]
)

python_library(
  name = 'goal_runner',
  sources = ['goal_runner.py'],
  dependencies = [
    ':command',
    '3rdparty/python/twitter/commons:twitter.common.lang',
    '3rdparty/python/twitter/commons:twitter.common.log',
    'src/python/pants/backend/core/tasks:common',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:address',
    'src/python/pants/base:config',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:target',
    'src/python/pants/base:workunit',
    'src/python/pants/engine',
    'src/python/pants/goal:context',
    'src/python/pants/goal:error',
    'src/python/pants/goal:initialize_reporting',
    'src/python/pants/goal',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/util:dirutil',
  ],
)
