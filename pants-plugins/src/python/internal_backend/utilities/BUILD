# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='plugin',
  dependencies=[
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/engine:target',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name="tests",
  dependencies=[
    ':plugin',
    'src/python/pants/base:revision',
  ],
  tags = {"type_checked"},
)
