# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='option',
  sources=globs('*.py'),
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.util',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:config',
    'src/python/pants/base:deprecated',
    'src/python/pants/goal',
  ]
)

target(
  name='migrate_config',
  dependencies=[
    'migrations/options/src/python:migrate_config'
  ]
)
