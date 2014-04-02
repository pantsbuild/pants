# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'engine',
  sources = globs('*.py'),
  dependencies = [
    pants('3rdparty/python:twitter.common.collections'),
    pants('3rdparty/python:twitter.common.lang'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/goal'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/tasks:check_exclusives'),
    pants('src/python/pants/tasks:task_error'),
  ],
)
