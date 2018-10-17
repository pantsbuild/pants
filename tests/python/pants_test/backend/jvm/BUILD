# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'jar_dependency_utils',
  sources = ['test_jar_dependency_utils.py'],
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/java/jar',
  ]
)

python_tests(
  name='integration',
  sources=globs('*_integration.py'),
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
  timeout=300
)