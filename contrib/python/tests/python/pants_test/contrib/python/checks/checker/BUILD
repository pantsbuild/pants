# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='lib',
  dependencies = [
    'contrib/python/src/python/pants/contrib/python/checks/checker',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/option',
  ],
)

python_tests(
  dependencies=[
    ':lib',
    'contrib/python/src/python/pants/contrib/python/checks/checker',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/option',
    'tests/python/pants_test:test_base',
  ]
)
