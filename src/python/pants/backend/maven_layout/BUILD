# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    ':maven_layout',
    'src/python/pants/build_graph',
  ]
)

python_library(
  name = 'maven_layout',
  sources = ['maven_layout.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
  ],
)
