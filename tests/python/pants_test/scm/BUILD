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
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('src/python/pants/scm'),
    pants('src/python/pants/scm:git'),
  ]
)
