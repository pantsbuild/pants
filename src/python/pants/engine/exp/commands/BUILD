# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name='list',
  source='commands.py',
  entry_point='pants.engine.exp.commands.commands:list',
  dependencies=[
    '3rdparty/python:beautifulsoup4',  # This is needed to satisfy pants-plugins deps.
    'src/python/pants/base:build_environment',
    'src/python/pants/bin:pants',
    'src/python/pants/engine/exp:mapper',
    'src/python/pants/engine/exp:targets',
  ]
)
