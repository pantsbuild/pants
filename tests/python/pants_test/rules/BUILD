# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name='filedeps',
  source='test_filedeps.py',
  dependencies=[
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/rules/core',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/engine:util',
  ]
)

python_tests(
  name='filedeps_integration',
  source='test_filedeps_integration.py',
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)

python_tests(
  name='test',
  source='test_test.py',
  dependencies=[
    'src/python/pants/build_graph',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/rules/core',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/engine:util',
  ]
)
