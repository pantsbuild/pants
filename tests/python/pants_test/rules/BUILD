# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

INTEGRATION_SOURCES = globs('*_integration.py')

python_tests(
  sources=globs('*.py', exclude=[INTEGRATION_SOURCES]),
  dependencies=[
    '3rdparty/python:future',
    '3rdparty/python:mock',
    'src/python/pants/backend/python/rules',
    'src/python/pants/util:objects',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/engine:scheduler_test_base',
    'tests/python/pants_test/engine/examples:scheduler_inputs',
  ]
)

python_tests(
  name='integration',
  sources=INTEGRATION_SOURCES,
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)
