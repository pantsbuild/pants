# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'linkify',
  sources = ['test_linkify.py'],
  dependencies = [
    'src/python/pants/reporting',
  ],
  timeout = 30,
)

python_tests(
  name = 'reporting',
  sources = ['test_reporting.py'],
  dependencies = [
    '3rdparty/python:requests',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/reporting',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:test_base',
  ],
)

python_tests(
  name = 'json_reporter',
  sources = ['test_json_reporter.py'],
  dependencies = [
    'src/python/pants/base:workunit',
    'src/python/pants/reporting',
    'src/python/pants/testutil:test_base',
  ],
)
