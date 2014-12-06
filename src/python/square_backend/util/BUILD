# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py', 'exclude_globally.py'],
  dependencies = [
    '3rdparty/python/square_backend:pyyaml',
    'src/python/pants/backend/jvm/targets:all',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:build_environment',
    ]
)
