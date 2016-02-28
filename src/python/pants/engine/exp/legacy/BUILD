# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='legacy',
  sources=globs('*.py'),
  dependencies=[
    '3rdparty/python:beautifulsoup4',  # This is needed to satisfy pants-plugins deps.
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_target_factory',
    'src/python/pants/base:parse_context',
    'src/python/pants/base:specs',
    'src/python/pants/bin:pants',
    'src/python/pants/engine/exp:fs',
    'src/python/pants/engine/exp:graph',
    'src/python/pants/engine/exp:mapper',
    'src/python/pants/engine/exp:nodes',
    'src/python/pants/engine/exp:parsers',
    'src/python/pants/engine/exp:scheduler',
    'src/python/pants/engine/exp:struct',
    'src/python/pants/option',
    'src/python/pants/util:memo',
    'src/python/pants/util:objects',
  ],
)

python_binary(
  name='list',
  entry_point='pants.engine.exp.legacy.commands:list',
  dependencies=[
    ':legacy'
  ]
)
