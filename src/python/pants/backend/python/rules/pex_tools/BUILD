# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='pex_tool',
  sources=[
    'pex_tool.py',
  ],
  dependencies=[
    '3rdparty/python:setuptools',
    'src/python/pants/engine:fs',
  ],
  tags = {'type_checked'},
)

python_library(
  name='common',
  sources=[
    'common.py',
  ],
  dependencies=[
    '3rdparty/python:dataclasses',
    '3rdparty/python:pex',
  ],
  tags = {'type_checked'},
)

python_library(
  name='resolver',
  sources=[
    'resolver.py',
  ],
  dependencies=[
    '3rdparty/python:pex',
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name='resolver-bin',
  entry_point='pants.backend.python.rules.pex_tools.resolver:main',
  dependencies=[
    ':resolver'
  ],
)

python_library(
  name='builder',
  sources=[
    'builder.py',
  ],
  dependencies=[
    '3rdparty/python:pex',
    ':common',
  ],
  tags = {'type_checked'},
)

python_binary(
  name='builder-bin',
  entry_point='pants.backend.python.rules.pex_tools.builder:main',
  dependencies=[
    ':builder',
  ],
)
