# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'python',
  sources = globs('*.py'),
  dependencies = [
    pants('src/python/pants/BUILD.commons:twitter.common.collections'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/python:interpreter_cache'),
    pants('src/python/pants/targets:python'),
    pants('src/python/pants/tasks:common'),
  ]
)
