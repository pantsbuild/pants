# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'jar',
  sources = globs('*.py'),
  dependencies = [
    pants('3rdparty/python:twitter.common.collections'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('3rdparty/python:twitter.common.lang'),
    pants('src/python/pants/java:jar'),
  ]
)
