# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    ':source_root',
    ':source_root_layout',
    'src/python/pants/base:build_file_aliases',
  ]
)

python_library(
  name = 'source_root',
  sources = ['source_root.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_manual',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:parse_context',
    '3rdparty/python/twitter/commons:twitter.common.collections',
  ],
)

python_library(
  name = 'source_root_layout',
  sources = ['source_root_layout.py'],
  dependencies = [
    ':source_root',
    'src/python/pants/base:layout'
  ],
)

