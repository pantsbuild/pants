# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'cache',
  sources = globs('*.py'),
  dependencies = [
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('src/python/pants/base:build_invalidator'),
    pants('src/python/pants/cache'),
    pants('tests/python/pants/testutils'),
  ]
)
