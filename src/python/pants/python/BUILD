# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  dependencies=[
    '3rdparty/python:pex',
    '3rdparty/python:setuptools',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/backend/python/subsystems/ipex',
    'src/python/pants/build_graph',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:ordered_set',
  ]
)


python_tests(
  name='tests',
  sources=['*_test.py', '!*_integration.py'],
  dependencies=[
    '3rdparty/python:pex',
    ':python',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:pexrc_util',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)


python_tests(
  name='integration',
  sources=['*_integration.py'],
  dependencies=[
    '3rdparty/python:pex',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:python_targets_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)
