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
    'src/python/pants/bin:pants',
    'src/python/pants/engine/exp:mapper',
    'src/python/pants/engine/exp:objects',
    'src/python/pants/engine/exp:targets',
    'src/python/pants/util:memo',
  ]
)

python_binary(
  name='list',
  entry_point='pants.engine.exp.legacy.commands:list',
  dependencies=[
    ':legacy'
  ]
)