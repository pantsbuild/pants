# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='address_mapper',
  sources=['address_mapper.py'],
  dependencies=[
    'src/python/pants/base:build_file',
    'src/python/pants/base:specs',
    'src/python/pants/build_graph',
    'src/python/pants/engine:build_files',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:nodes',
    'src/python/pants/engine:selectors',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='parser',
  sources=['parser.py'],
  dependencies=[
    ':structs',
    'src/python/pants/base:build_file_target_factory',
    'src/python/pants/base:parse_context',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:objects',
    'src/python/pants/engine:parser',
    'src/python/pants/util:memo',
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
    'src/python/pants/engine:fs',
    'src/python/pants/engine:nodes',
    'src/python/pants/engine:struct',
    'src/python/pants/source',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
    'src/python/pants/util:objects',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='graph',
  sources=['graph.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:dataclasses',
    ':address_mapper',
    ':structs',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:parse_context',
    'src/python/pants/build_graph',
    'src/python/pants/engine:build_files',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:objects',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:selectors',
    'src/python/pants/option',
    'src/python/pants/scm/subsystems:changed',
    'src/python/pants/source',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='tests',
  dependencies=[
    ':graph'
  ],
  tags = {"partially_type_checked"},
)
