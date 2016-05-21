# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_binary(
  name='compare_config',
  source='compare_config.py',
  dependencies=[
    'src/python/pants/option',
  ]
)


python_binary(
  name='migrate_config',
  source='migrate_config.py',
  dependencies=[
    '3rdparty/python:ansicolors',
    'src/python/pants/option',
  ]
)
