# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='goal',
  dependencies=[
    ':context',
    ':products',
    ':run_tracker',
    ':union_products',
  ]
)

python_tests(
  name='context',
  sources=['test_context.py'],
  dependencies=[
    'src/python/pants/base:address',
    'src/python/pants/base:target',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='products',
  sources=['test_products.py'],
  dependencies=[
    'src/python/pants/goal:products',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='run_tracker',
  sources=['test_run_tracker.py'],
  dependencies=[
    '3rdparty/python:mock',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='union_products',
  sources=['test_union_products.py'],
  dependencies=[
    'src/python/pants/goal:products',
    'tests/python/pants_test:base_test',
  ],
)
