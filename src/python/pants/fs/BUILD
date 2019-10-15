# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:strutil',
  ]
)

python_tests(
  name = "tests",
  dependencies = [
    'tests/python/pants_test:console_rule_test_base',
    'tests/python/pants_test/engine:util'
  ]
)
