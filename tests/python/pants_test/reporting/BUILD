# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'reporting',
  sources = ['test_linkify.py'],
  dependencies = [
    'src/python/pants/reporting',
  ],
)

python_tests(
  name = 'reporting_integration',
  sources = ['test_reporting_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
  timeout = 120,
)
