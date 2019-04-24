# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'linkify',
  sources = ['test_linkify.py'],
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/reporting',
  ],
  timeout = 10,
)

python_tests(
  name = 'reporting_integration',
  sources = ['test_reporting_integration.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:parameterized',
    '3rdparty/python:py-zipkin',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
  timeout = 600,
)

python_tests(
  name = 'reporting',
  sources = ['test_reporting.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:requests',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/reporting',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:test_base',
  ],
)

python_tests(
  name = 'json_reporter',
  sources = ['test_json_reporter.py'],
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/base:workunit',
    'src/python/pants/reporting',
    'tests/python/pants_test:test_base',
  ],
)
