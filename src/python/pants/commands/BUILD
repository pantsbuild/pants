# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'command',
  sources = ['command.py', 'register.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:target'),
  ]
)

python_library(
  name = 'pants_old',
  dependencies = [
    pants(':build'),
    pants(':py'),
    pants(':setup_py'),
  ]
)

python_library(
  name = 'pants_new',
  dependencies = [
    pants(':goal'),
  ]
)

python_library(
  name = 'build',
  sources = ['build.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/python:python_builder'),
    pants('src/python/pants/python:interpreter_cache'),
  ]
)

python_library(
  name = 'py',
  sources = ['py.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/python:python_chroot'),
    pants('src/python/pants/python:interpreter_cache'),
    pants('src/python/pants/targets:python'),
  ]
)

python_library(
  name = 'setup_py',
  sources = ['setup_py.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/python:antlr_builder'),
    pants('src/python/pants/python:thrift_builder'),
    pants('src/python/pants/targets:python'),
  ]
)

python_library(
  name = 'goal',
  sources = ['goal.py'],
  dependencies = [
    pants(':command'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:rcfile'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/engine'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/goal:help'),
    pants('src/python/pants/goal:initialize_reporting'),
    pants('src/python/pants/goal:option_helpers'),
    pants('src/python/pants/goal:register'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/tasks:common'),
    pants('src/python/pants/tasks:console_task'),
    pants('src/python/pants/tasks:nailgun_task'),
  ],
)
