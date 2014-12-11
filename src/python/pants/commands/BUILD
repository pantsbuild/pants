# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'goal_runner',
  sources = ['goal_runner.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.lang',
    '3rdparty/python/twitter/commons:twitter.common.log',
    'src/python/pants/backend/core/tasks:common',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_address_mapper',
    'src/python/pants/base:build_file_parser',
    'src/python/pants/base:build_graph',
    'src/python/pants/base:config',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:extension_loader',
    'src/python/pants/base:target',
    'src/python/pants/base:workunit',
    'src/python/pants/engine',
    'src/python/pants/goal',
    'src/python/pants/goal:context',
    'src/python/pants/goal:initialize_reporting',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/util:dirutil',
  ],
)
