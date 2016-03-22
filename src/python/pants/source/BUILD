# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='source',
  sources=globs('*.py'),
  dependencies=[
    '3rdparty/python:six',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/base:build_environment',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/util:memo',
  ]
)
