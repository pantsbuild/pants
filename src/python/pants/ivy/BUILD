# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'ivy',
  sources = globs('*.py'),
  dependencies = [
    pants('3rdparty/python:twitter.common.collections'),
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('3rdparty/python:twitter.common.lang'),
    pants('3rdparty/python:twitter.common.log'),
    pants('3rdparty/python:twitter.common.quantity'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/java:executor'),
    pants('src/python/pants/java:util'),
    pants('src/python/pants/net'),
  ]
)
