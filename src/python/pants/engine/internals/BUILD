# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='tests',
  dependencies=[
    ':graph',
    ':options_parsing',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/init',
    'src/python/pants/option',
    'src/python/pants/testutil:test_base',
    'src/python/pants/util:logging',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"type_checked"},
)

python_library(
  name='graph',
  sources=['graph.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:specs',
    'src/python/pants/engine/legacy:address_mapper',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/option',
    'src/python/pants/source',
    'src/python/pants/util:meta',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='options_parsing',
  sources=['options_parsing.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/build_graph',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:objects',
    'src/python/pants/option',
    'src/python/pants/util:logging',
  ],
  tags = {"partially_type_checked"},
)
