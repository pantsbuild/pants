# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources = [
    'python_app.py',
    'python_binary.py',
    'python_distribution.py',
    'python_library.py',
    'python_requirement_library.py',
    'python_target.py',
    'python_tests.py',
  ],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:pex',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/build_graph',
  ],
)


# TODO: Old name.  Remove after all references are fixed to refer directly to the target above.
target(
  name = 'python',
  dependencies = [':targets'],
)
