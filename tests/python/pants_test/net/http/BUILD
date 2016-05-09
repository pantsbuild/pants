# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'http',
  sources = globs('*.py'),
  dependencies = [
    '3rdparty/python:mox',
    '3rdparty/python:requests',
    '3rdparty/python:six',
    'src/python/pants/net',
    'src/python/pants/util:contextutil',
  ],
)
