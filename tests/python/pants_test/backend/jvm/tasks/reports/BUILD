# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'reports',
  sources = ['test_junit_html_report.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:reports',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:strutil',
    'tests/python/pants_test:test_infra',
  ]
)
