# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='option',
  sources=globs('*.py'),
  dependencies = [
    '3rdparty/python:six',
    '3rdparty/python:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/util:eval',
    'src/python/pants/util:meta',
    'src/python/pants/util:strutil',
  ],
)

target(
  name='migrate_config',
  dependencies=[
    'migrations/options/src/python:migrate_config'
  ]
)
