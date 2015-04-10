# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    ':maven_layout',
    'src/python/pants/base:build_file_aliases',
  ]
)

python_library(
  name = 'maven_layout',
  sources = ['maven_layout.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/targets:python',
    'src/python/pants/backend/core/targets:all',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/build_file_layout:source_root',
  ],
)
