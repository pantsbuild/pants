# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'reporting',
  sources = globs('*.py'),
  resources = rglobs('assets/*') + globs('templates/*.mustache'),
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.threading'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:mustache'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/goal:run_tracker'),  # XXX
    pants('3rdparty/python:ansicolors'),
    pants('3rdparty/python:pystache'),
  ]
)
