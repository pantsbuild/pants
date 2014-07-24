# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'cache',
  sources = globs('*.py'),
  dependencies = [
    pants('src/python/pants/base:build_invalidator'),
    pants('src/python/pants/cache'),
    pants('src/python/pants/util:contextutil'),
    pants('src/python/pants/util:dirutil'),
    pants('tests/python/pants_test:base_test'),
    pants('tests/python/pants_test/testutils'),
  ]
)
