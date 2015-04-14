# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'option',
  sources = globs('*.py', exclude=[['migrate_config.py']]),
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:config',
    'src/python/pants/base:deprecated',
    'src/python/pants/goal',
  ]
)

python_binary(
  name= 'migrate_config',
  source = 'migrate_config.py',
  dependencies = [
    ':option',
    '3rdparty/python:ansicolors',
    'src/python/pants/base:config',
  ]
)
