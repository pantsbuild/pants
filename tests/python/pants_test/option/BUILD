# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'option',
  sources = globs('*.py'),
  dependencies = [
    '3rdparty/python:pytest',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name='testing',
  sources=globs('*.py'),
  dependencies=[
    'src/python/pants/option',
  ],
)