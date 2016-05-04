# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='parser',
  sources=['parser.py'],
  dependencies=[
    ':structs',
    'src/python/pants/base:build_file_target_factory',
    'src/python/pants/base:parse_context',
    'src/python/pants/engine/exp:fs',
    'src/python/pants/engine/exp:parser',
  ],
)

python_library(
  name='structs',
  sources=['structs.py'],
  dependencies=[
    'src/python/pants/engine/exp:fs',
    'src/python/pants/engine/exp:objects',
    'src/python/pants/engine/exp:struct',
    'src/python/pants/source',
    'src/python/pants/util:meta',
  ],
)

python_library(
  name='graph',
  sources=['graph.py'],
  dependencies=[
    ':parser',
    ':structs',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/engine/exp:graph',
    'src/python/pants/engine/exp:parser',
    'src/python/pants/engine/exp:selectors',
    'src/python/pants/source',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:objects',
  ],
)

python_library(
  name='commands',
  sources=['commands.py'],
  dependencies=[
    '3rdparty/python:beautifulsoup4',  # This is needed to satisfy pants-plugins deps.
    ':graph',
    ':parser',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:specs',
    'src/python/pants/bin',
    'src/python/pants/engine/exp:fs',
    'src/python/pants/engine/exp:graph',
    'src/python/pants/engine/exp:mapper',
    'src/python/pants/engine/exp:scheduler',
    'src/python/pants/engine/exp:storage',
    'src/python/pants/option',
    'src/python/pants/util:memo',
  ],
)

python_binary(
  name='dependencies',
  entry_point='pants.engine.exp.legacy.commands:dependencies',
  dependencies=[
    ':commands'
  ]
)

python_binary(
  name='filemap',
  entry_point='pants.engine.exp.legacy.commands:filemap',
  dependencies=[
    ':commands'
  ]
)

python_binary(
  name='fsnodes',
  entry_point='pants.engine.exp.legacy.commands:fsnodes',
  dependencies=[
    ':commands'
  ]
)
