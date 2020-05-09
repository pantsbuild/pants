# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources = ['*.py', '!register.py', '!*_test.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/engine:target',
    'src/python/pants/util:frozendict',
  ],
  tags = {"type_checked"},
)

python_library(
  name = 'plugin',
  sources = ['register.py'],
  dependencies = [
    ':core',
    'src/python/pants/core/goals',
    'src/python/pants/core/util_rules',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:target',
  ],
  tags = {"type_checked"},
)
