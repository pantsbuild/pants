# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'changed',
  sources = ['changed.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/engine:addresses',
    'src/python/pants/goal:workspace',
    'src/python/pants/subsystem',
  ],
  tags = {"partially_type_checked"},
)
