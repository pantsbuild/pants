# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='lib',
  dependencies=[
    'contrib/go/src/python/pants/contrib/go:plugin',
    'src/python/pants/build_graph',
    'src/python/pants/util:meta',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  dependencies=[
    ':lib',
    'contrib/go/src/python/pants/contrib/go:plugin',
    'contrib/go/src/python/pants/contrib/go/targets',
    'src/python/pants/build_graph',
    'tests/python/pants_test:base_test',
  ]
)
