# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pants_old',
  dependencies = [
    ':build',
    ':py',
    ':setup_py',
  ]
)

python_library(
  name = 'build',
  sources = ['build.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:address',
    'src/python/pants/base:config',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:target',
    'src/python/pants/commands:command',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:python_builder',
    'src/python/pants/backend/core/targets:common',
  ]
)

python_library(
  name = 'py',
  sources = ['py.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.python',
    'src/python/pants/base:address',
    'src/python/pants/base:config',
    'src/python/pants/base:target',
    'src/python/pants/commands:command',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:python_chroot',
  ]
)

python_library(
  name = 'setup_py',
  sources = ['setup_py.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python/twitter/commons:twitter.common.python',
    'src/python/pants/base:address',
    'src/python/pants/base:config',
    'src/python/pants/base:target',
    'src/python/pants/commands:command',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:antlr_builder',
    'src/python/pants/backend/python:thrift_builder',
    'src/python/pants/util:dirutil',
  ]
)
