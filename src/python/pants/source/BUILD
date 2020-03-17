# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources = ['*.py', '!payload_fields.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:dataclasses',
    '3rdparty/python:typing-extensions',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:project_tree',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:native',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'payload_fields',
  sources = ['payload_fields.py'],
  dependencies = [
    ':source',
    'src/python/pants/engine:fs',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'tests',
  dependencies = [
    ':source',
    ':payload_fields',
    'src/python/pants/base:payload',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)
