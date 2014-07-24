# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'scm',
  dependencies = [
    pants(':test_git'),
  ]
)

python_tests(
  name = 'test_git',
  sources = ['test_git.py'],
  dependencies = [
    pants('src/python/pants/scm'),
    pants('src/python/pants/scm:git'),
    pants('src/python/pants/util:contextutil'),
    pants('src/python/pants/util:dirutil'),
  ]
)
