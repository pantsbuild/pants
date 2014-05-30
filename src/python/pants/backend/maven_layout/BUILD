# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    ':maven_layout',
  ]
)

python_library(
  name = 'maven_layout',
  sources = ['maven_layout.py'],
  dependencies = [
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/codegen/targets:python'),
    pants('src/python/pants/backend/core/targets:all'),
    pants('src/python/pants/base:source_root'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/backend/python/targets:python'),
  ],
)
