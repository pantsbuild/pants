# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:strutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name="tests",
  dependencies = [
    ':scm',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:git_util'
  ],
  tags = {"partially_type_checked"},
)
