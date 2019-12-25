# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:isolated_process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/rules/core',
    'src/python/pants/source:source',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='tests',
  sources=globs('*_test.py', exclude=[globs('*_integration_test.py')]),
  dependencies=[
    ':rules',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/build_graph',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:isolated_process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/rules/core',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
  ],
  tags = {"partially_type_checked"},
)


python_tests(
  name='integration',
  sources=globs('*_integration_test.py'),
  dependencies=[
    'src/python/pants/testutil:int-test',
    'testprojects/tests/python/pants:dummies_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
  timeout = 120,
)
