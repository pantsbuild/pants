# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='lib',
  dependencies = [
    'contrib/python/src/python/pants/contrib/python/checks/checker',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/option',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  dependencies=[
    ':lib',
    'contrib/python/src/python/pants/contrib/python/checks/checker',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)
