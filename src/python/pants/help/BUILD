# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:typing-extensions',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/util:collections',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='tests',
  sources=globs('*_test.py', exclude=[globs('*_integration_test.py')]),
  dependencies=[
    'src/python/pants/build_graph',
    'src/python/pants/help',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/task',
    'src/python/pants/util:collections',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='integration',
  sources=globs('*_integration_test.py'),
  dependencies=[
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)
