# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='go_distribution',
  sources=['go_distribution.py'],
  dependencies=[
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/fs',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
  ],
)

python_library(
  name='fetchers',
  sources=['fetchers.py'],
  dependencies=[
    '3rdparty/python:requests',
    '3rdparty/python:six',
    'src/python/pants/fs',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
  ],
)