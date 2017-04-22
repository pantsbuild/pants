# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=globs('*.py'),  # Need explicit sources, because `go_test.py` won't match the default.
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:ansicolors',
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'contrib/go/src/python/pants/contrib/go/targets',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:thrift_util',
    'src/python/pants/build_graph',
    'src/python/pants/process',
    'src/python/pants/source',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/option',
  ]
)
