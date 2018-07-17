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
    '3rdparty/python:future',
    '3rdparty/python:six',
    'src/python/pants/build_graph',
    'src/python/pants/engine:objects',
    'src/python/pants/engine:parser',
    'src/python/pants/util:memo',
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
    'src/python/pants/util:objects',
  ]
)

resources(
  name='fs_test',
  # Note that this test data dir is bundled into a tarfile, to preserve symlink structure
  # when copied into a chroot.
  sources=rglobs('fs_test/*')
)

resources(
  name='graph_test',
  sources=rglobs('graph_test/*')
)

resources(
  name='mapper_test',
  sources=rglobs('mapper_test/*')
)

resources(
  name='scheduler_inputs',
  sources=rglobs('scheduler_inputs/*')
)
