# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'ivy',
  dependencies = [
    ':bootstrapper',
  ],
)

python_tests(
  name='bootstrapper',
  sources = [ 'test_bootstrapper.py' ],
  dependencies = [
    'src/python/pants/ivy',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ]
)
