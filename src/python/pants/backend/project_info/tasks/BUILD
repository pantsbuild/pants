# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all',
  dependencies = [
    ':depmap',
  ],
)

python_library(
  name = 'depmap',
  sources = ['depmap.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
  ],
  tags = {"partially_type_checked"},
)
