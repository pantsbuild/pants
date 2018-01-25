# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Example of defining a test target that depends on a python_dist target.

python_tests(
  name='fasthello',
  sources=[
    'test_fasthello.py'
  ],
  dependencies=[
    'examples/src/python/example/python_distribution/hello/fasthello:fasthello'
  ]
)
