# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'command',
  sources = ['command.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:build_file_parser'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:build_graph'),
  ]
)

python_library(
  name = 'pants_new',
  dependencies = [
    pants(':goal'),
  ]
)

python_library(
  name = 'goal',
  sources = ['goal.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:cmd_line_spec_parser'),
    pants('src/python/pants/base:rcfile'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/engine'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/goal:context'),
    pants('src/python/pants/goal:help'),
    pants('src/python/pants/goal:initialize_reporting'),
    pants('src/python/pants/goal:option_helpers'),
    pants('src/python/pants/backend/jvm/tasks:nailgun_task'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/backend/core/tasks:common'),
    pants('src/python/pants/backend/core/tasks:console_task'),
    pants('src/python/pants/util:dirutil'),
  ],
)
