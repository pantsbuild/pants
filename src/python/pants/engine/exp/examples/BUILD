# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='planners',
  sources=['planners.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/engine/exp:addressable',
    'src/python/pants/engine/exp:configuration',
    'src/python/pants/engine/exp:graph',
    'src/python/pants/engine/exp:mapper',
    'src/python/pants/engine/exp:parsers',
    'src/python/pants/engine/exp:scheduler',
    'src/python/pants/engine/exp:targets',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name='visualizer',
  sources=['visualizer.py'],
  dependencies=[
    ':planners',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/build_graph',
    'src/python/pants/engine/exp:scheduler',
    'src/python/pants/util:contextutil',
  ]
)

python_binary(
  name='viz',
  entry_point='pants.engine.exp.examples.visualizer:main',
  dependencies=[
    ':visualizer'
  ]
)
