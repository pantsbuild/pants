# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/build_graph',
    'src/python/pants/engine:rules',
    'src/python/pants/subsystem',
    'src/python/pants/util:ordered_set',
    'src/python/pants:version',
  ],
)

python_tests(
  name="tests",
  dependencies=[
    '3rdparty/python:setuptools',
    ':utilities',
  ],
)
