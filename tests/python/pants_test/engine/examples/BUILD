# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

page(
  name='readme',
  source='README.md',
)

python_library(
  name='parsers',
  sources=['parsers.py'],
  dependencies=[
    '3rdparty/python:six',
    'src/python/pants/build_graph',
    'src/python/pants/engine:objects',
    'src/python/pants/engine:parser',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name='planners',
  sources=['planners.py'],
  dependencies=[
    ':graph_validator',
    ':parsers',
    ':sources',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:file_system_project_tree',
    'src/python/pants/build_graph',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:graph',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:nodes',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:scheduler',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:storage',
    'src/python/pants/engine:struct',
  ]
)

python_library(
  name='graph_validator',
  sources=['graph_validator.py'],
  dependencies=[
    'src/python/pants/engine:nodes',
  ]
)

python_library(
  name='sources',
  sources=['sources.py'],
  dependencies=[
    'src/python/pants/engine:addressable',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:struct',
    'src/python/pants/source',
  ]
)

python_library(
  name='visualizer',
  sources=['visualizer.py'],
  dependencies=[
    ':planners',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/build_graph',
    'src/python/pants/engine:engine',
    'src/python/pants/engine:scheduler',
    'src/python/pants/util:contextutil',
  ]
)

python_binary(
  name='viz',
  entry_point='pants_test.engine.examples.visualizer:main_addresses',
  dependencies=[
    ':visualizer'
  ]
)

python_binary(
  name='viz-fs',
  entry_point='pants_test.engine.examples.visualizer:main_filespecs',
  dependencies=[
    ':visualizer'
  ]
)
