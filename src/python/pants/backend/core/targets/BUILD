# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':common',
  ],
)

python_library(
  name = 'common',
  sources = [
    'dependencies.py',
    'doc.py',
    'prep_command.py',
    'resources.py',
  ],
  dependencies = [
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:target',
  ],
)
