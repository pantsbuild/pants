# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:strutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = "tests",
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil:goal_rule_test_base',
    'src/python/pants/testutil/engine:util',
  ],
  tags = {"partially_type_checked"},
)
