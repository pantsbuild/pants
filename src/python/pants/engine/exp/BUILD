# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='addressable',
  sources=['addressable.py'],
  dependencies=[
    '3rdparty/python:six',
  ]
)

python_library(
  name='graph',
  sources=['graph.py'],
  dependencies=[
    '3rdparty/python:six',
    ':addressable',
    ':mapper',
    ':serializable',
    'src/python/pants/base:address',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name='mapper',
  sources=['mapper.py'],
  dependencies=[
    ':parsers',
    ':serializable',
    'src/python/pants/base:address',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name='parsers',
  sources=['parsers.py'],
  dependencies=[
    '3rdparty/python:six',
    ':serializable',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name='serializable',
  sources=['serializable.py'],
  dependencies=[
    'src/python/pants/util:meta',
  ]
)

python_library(
  name='targets',
  sources=['targets.py'],
  dependencies=[
    ':addressable',
    ':serializable',
  ]
)
