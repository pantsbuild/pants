# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:ansicolors',
    '3rdparty/python:dataclasses',
    '3rdparty/python:typing-extensions',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/engine:goal',
    'src/python/pants/engine:unions',
    'src/python/pants/goal',
    'src/python/pants/option:global_options',
    'src/python/pants/option',
    'src/python/pants/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='tests',
  sources=['*_test.py', '!*_integration_test.py'],
  dependencies=[
    ':help',
    '3rdparty/python:dataclasses',
    'src/python/pants/option',
    'src/python/pants/option:global_options',
    'src/python/pants/subsystem',
    'src/python/pants/task',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='integration',
  sources=['*_integration_test.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration', 'partially_type_checked'},
)
