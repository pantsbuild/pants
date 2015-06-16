# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='goal',
  sources=globs('*.py'),
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/core/tasks:group_task',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/base:address',
    'src/python/pants/base:target',
    'src/python/pants/goal',
    'src/python/pants/goal:products',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'tests/python/pants_test:base_test',
  ]
)
