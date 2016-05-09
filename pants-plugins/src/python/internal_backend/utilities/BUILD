# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='plugin',
  sources=['register.py'],
  dependencies = [
    '3rdparty/python:twitter.common.collections',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
  ],
)

