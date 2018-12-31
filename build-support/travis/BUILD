# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    ':templates',
    '3rdparty/python:pystache',
    '3rdparty/python:setuptools',
  ]
)

python_binary(
  name='generate_travis_yml',
  # We're not under any registered source root, so the entry point is relative to this dir.
  entry_point='generate_travis_yml_main',  
  dependencies=[
    ':travis',
  ]
)

resources(
  name='templates',
  sources=globs('*.mustache')
)
