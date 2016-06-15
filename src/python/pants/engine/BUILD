# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

page(
  name='readme',
  source='README.md',
)

python_library(
  name = 'legacy_engine',
  sources = ['legacy_engine.py', 'round_engine.py', 'round_manager.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/goal',
    'src/python/pants/util:meta',
  ],
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
    'src/python/pants/base:project_tree',
    'src/python/pants/build_graph',
  ]
)

python_library(
  name='mapper',
  sources=['mapper.py'],
  dependencies=[
    ':objects',
    ':parser',
    'src/python/pants/build_graph',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name='nodes',
  sources=['nodes.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':addressable',
    ':fs',
    ':struct',
    'src/python/pants/base:project_tree',
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
  name='parser',
  sources=['parser.py'],
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
  dependencies=[
    '3rdparty/python:futures',
  ]
)

python_library(
  name='selectors',
  sources=['selectors.py'],
  dependencies=[
    'src/python/pants/util:memo',
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
  name='storage',
  sources=['storage.py'],
  dependencies=[
    ':objects',
    ':scheduler',
    '3rdparty/python:lmdb',
    'src/python/pants/util:dirutil'
  ]
)
