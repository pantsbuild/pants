# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pantsd',
  sources = rglobs('*.py'),
  dependencies = [
    '3rdparty/python:psutil',
    '3rdparty/python:setproctitle',
    'src/python/pants/base:build_environment',
    'src/python/pants/logging:logging',
    'src/python/pants/subsystem:subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:meta'
  ]
)
