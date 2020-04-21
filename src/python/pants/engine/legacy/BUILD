# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='tests',
  dependencies=[
    ':address_mapper',
    ':graph',
    ':parser',
    ':round_engine',
    ':structs',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph',
    'src/python/pants/engine/internals:core_abstractions',
    'src/python/pants/engine:fs',
    'src/python/pants/goal',
    'src/python/pants/option',
    'src/python/pants/task',
    'src/python/pants/testutil/engine:engine_test_base',
    'src/python/pants/testutil:test_base',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  tags = {"type_checked"},
)

python_library(
  name='address_mapper',
  sources=['address_mapper.py'],
  dependencies=[
    'src/python/pants/base:build_file',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph',
    'src/python/pants/engine:addresses',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='graph',
  sources=['graph.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    ':structs',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:parse_context',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph',
    'src/python/pants/engine/internals:core_abstractions',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:collection',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/option',
    'src/python/pants/source',
    'src/python/pants/util:meta',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='parser',
  sources=['parser.py'],
  dependencies=[
    ':structs',
    'src/python/pants/base:build_file_target_factory',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:parse_context',
    'src/python/pants/build_graph',
    'src/python/pants/engine/internals:core_abstractions',
    'src/python/pants/option',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'round_engine',
  sources = ['round_engine.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/goal',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='structs',
  sources=['structs.py'],
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/base:deprecated',
    'src/python/pants/build_graph',
    'src/python/pants/engine/internals:core_abstractions',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:unions',
    'src/python/pants/source',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:meta',
    'src/python/pants/util:objects',
  ],
  tags = {"partially_type_checked"},
)
