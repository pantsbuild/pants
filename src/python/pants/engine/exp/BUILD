# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

page(
  name='readme',
  source='README.md',
)

python_library(
  name='addressable',
  sources=['addressable.py'],
  dependencies=[
    '3rdparty/python:six',
    ':objects',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name='struct',
  sources=['struct.py'],
  dependencies=[
    ':addressable',
    ':objects',
  ]
)

python_library(
  name='engine',
  sources=['engine.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':objects',
    ':processing',
    ':storage',
    'src/python/pants/base:exceptions',
    'src/python/pants/util:meta',
  ]
)

python_library(
  name='fs',
  sources=['fs.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:project_tree',
    'src/python/pants/source',
    'src/python/pants/util:meta',
    'src/python/pants/util:objects',
  ]
)

python_library(
  name='graph',
  sources=['graph.py'],
  dependencies=[
    '3rdparty/python:six',
    ':addressable',
    ':fs',
    ':mapper',
    ':objects',
    ':selectors',
    'src/python/pants/build_graph',
  ]
)

python_library(
  name='mapper',
  sources=['mapper.py'],
  dependencies=[
    ':objects',
    ':parsers',
    'src/python/pants/build_graph',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name='nodes',
  sources=['nodes.py'],
  dependencies=[
    ':addressable',
    ':fs',
    ':objects',
    ':struct',
    ':storage',
    'src/python/pants/build_graph',
    'src/python/pants/util:objects',
  ]
)

python_library(
  name='objects',
  sources=['objects.py'],
  dependencies=[
    'src/python/pants/util:meta',
  ]
)

python_library(
  name='parsers',
  sources=['parsers.py'],
  dependencies=[
    '3rdparty/python:six',
    ':objects',
    'src/python/pants/build_graph',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name='processing',
  sources=['processing.py'],
)

python_library(
  name='register',
  sources=['register.py'],
  dependencies=[
    ':addressable',
    ':fs',
    ':graph',
    ':mapper',
    ':selectors',
    ':struct',
    'src/python/pants/engine/exp/legacy:graph',
    'src/python/pants/engine/exp/legacy:parser',
  ]
)

python_library(
  name='selectors',
  sources=['selectors.py'],
  dependencies=[
    ':nodes',
    'src/python/pants/util:meta',
    'src/python/pants/util:objects',
  ]
)

python_library(
  name='scheduler',
  sources=['scheduler.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':addressable',
    ':fs',
    ':nodes',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph',
    'src/python/pants/util:objects',
  ]
)

python_library(
  name='sources',
  sources=['sources.py'],
  dependencies=[
    ':addressable',
    ':fs',
    ':struct',
    'src/python/pants/source',
  ]
)

python_library(
  name='storage',
  sources=['storage.py'],
  dependencies=[
    ':objects',
    '3rdparty/python:lmdb',
    'src/python/pants/util:dirutil'
  ]
)
