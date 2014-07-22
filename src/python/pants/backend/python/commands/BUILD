# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pants_old',
  dependencies = [
    pants(':build'),
    pants(':py'),
    pants(':setup_py'),
  ]
)

python_library(
  name = 'build',
  sources = ['build.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:cmd_line_spec_parser'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/commands:command'),
    pants('src/python/pants/backend/python:interpreter_cache'),
    pants('src/python/pants/backend/python:python_builder'),
    pants('src/python/pants/backend/core/targets:common'),
  ]
)

python_library(
  name = 'py',
  sources = ['py.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/commands:command'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/backend/python:interpreter_cache'),
    pants('src/python/pants/backend/python:python_chroot'),
  ]
)

python_library(
  name = 'setup_py',
  sources = ['setup_py.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/commands:command'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/backend/python:antlr_builder'),
    pants('src/python/pants/backend/python:thrift_builder'),
    pants('src/python/pants/util:dirutil'),
  ]
)
