# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    'src/python/pants/util:collections_abc_backport',
    '3rdparty/python:future',
    '3rdparty/python:ansicolors',
    '3rdparty/python:setuptools',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:hash_utils',
    'src/python/pants/engine:selectors',
    'src/python/pants/util:eval',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
    'src/python/pants/util:objects',
    'src/python/pants/util:py2_compat',
    'src/python/pants/util:strutil',
  ]
)

target(
  name='migrate_config',
  dependencies=[
    'migrations/options/src/python:migrate_config'
  ]
)
