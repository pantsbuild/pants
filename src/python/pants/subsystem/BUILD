# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/option',
    'src/python/pants/util:ordered_set',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='tests',
  dependencies=[
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)
