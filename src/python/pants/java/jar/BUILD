# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='manifest',
  sources=['manifest.py'],
  dependencies=[
    '3rdparty/python:six',
  ]
)

python_library(
  name='shader',
  sources=['shader.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'src/python/pants/java/distribution',
    'src/python/pants/subsystem',
  ]
)
