# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
  name='structs',
  sources=['structs.py'],
  dependencies=[
    'src/python/pants/engine/internals:core_abstractions',
  ],
  tags = {"partially_type_checked"},
)
