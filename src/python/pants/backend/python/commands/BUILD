# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pants_old',
  dependencies = [
    ':setup_py',
  ]
)

python_library(
  name = 'setup_py',
  sources = ['setup_py.py'],
  dependencies = [
    '3rdparty/python:pex',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
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
