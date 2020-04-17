# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/engine:target',
    'src/python/pants/util:frozendict',
  ],
  tags = {"type_checked"},
)

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    ':core',
    'src/python/pants/core/goals',
    'src/python/pants/core/project_info',
    'src/python/pants/core/rule_utils',
    'src/python/pants/engine:target',
  ],
  tags = {"type_checked"},
)
