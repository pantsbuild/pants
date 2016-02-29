# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='parser',
  sources=['parser.py'],
  dependencies=[
    'src/python/pants/base:build_file_target_factory',
    'src/python/pants/base:parse_context',
    'src/python/pants/engine/exp:fs',
    'src/python/pants/engine/exp:parsers',
    'src/python/pants/engine/exp:struct',
  ],
)

python_library(
  name='graph',
  sources=['graph.py'],
  dependencies=[
    'src/python/pants/engine/exp:graph',
    'src/python/pants/engine/exp:selectors',
    'src/python/pants/util:objects',
  ],
)

python_library(
  name='commands',
  sources=['commands.py'],
  dependencies=[
    '3rdparty/python:beautifulsoup4',  # This is needed to satisfy pants-plugins deps.
    'src/python/pants/base:build_environment',
    'src/python/pants/base:specs',
    'src/python/pants/bin',
    'src/python/pants/engine/exp:mapper',
    'src/python/pants/engine/exp:scheduler',
    'src/python/pants/option',
    'src/python/pants/util:memo',
  ],
)

python_binary(
  name='list',
  entry_point='pants.engine.exp.legacy.commands:list',
  dependencies=[
    ':commands'
  ]
)
