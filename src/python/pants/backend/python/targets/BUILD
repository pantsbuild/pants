# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'python',
  sources = [
    'python_binary.py',
    'python_library.py',
    'python_requirement_library.py',
    'python_target.py',
    'python_tests.py',
  ],
  dependencies = [
    '3rdparty/python:pex',
    '3rdparty/python:six',
    '3rdparty/python:twitter.common.collections',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:validation',
    'src/python/pants/build_graph',
    'src/python/pants/util:memo',
  ],
)
