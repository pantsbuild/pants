# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'reporting',
  dependencies = [
    ':linkify',
    ':report',
  ]
)

python_tests(
  name = 'linkify',
  sources = ['test_linkify.py'],
  dependencies = [
    'src/python/pants/reporting',
  ]
)

python_tests(
  name = 'report',
  sources = ['test_report.py'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/base:workunit',
    'src/python/pants/reporting',
    'src/python/pants/util:contextutil',
  ]
)
