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
    'doc.py',
    'prep_command.py',
    'resources.py',
  ],
  dependencies = [
    'src/python/pants/backend/docgen/targets',
    'src/python/pants/base:deprecated',
    'src/python/pants/build_graph',
  ],
)
