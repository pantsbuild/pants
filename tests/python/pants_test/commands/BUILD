# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'integration',
  dependencies = [
    ':test_spec_exclude_integration',
  ]
)

python_tests(
  name = 'test_spec_exclude_integration',
  sources = [ 'test_spec_exclude_integration.py' ],
  dependencies = [
    'tests/python/pants_test:int-test',
  ]
)
