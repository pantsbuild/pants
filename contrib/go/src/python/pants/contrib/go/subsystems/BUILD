# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='subsystems',
  sources=globs('*.py'),
  dependencies=[
    '3rdparty/python:requests',
    '3rdparty/python:six',
    'contrib/go/src/python/pants/contrib/go/targets:go_remote_library',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/fs',
    'src/python/pants/option',
    'src/python/pants/scm:git',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
  ],
)
