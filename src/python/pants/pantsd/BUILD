# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'process_manager',
  sources = ['process_manager.py'],
  dependencies = [
    '3rdparty/python:psutil',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:deadline',
    'src/python/pants/util:dirutil'
  ]
)

python_library(
  name = 'watchman',
  sources = ['watchman.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
    ':process_manager',
    ':watchman_client'
  ]
)

python_library(
  name = 'watchman_client',
  sources = ['watchman_client.py'],
  dependencies = [
    '3rdparty/python:pywatchman'
  ]
)
