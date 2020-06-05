# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='plugin',
  sources=['register.py'],
  dependencies=[
    'src/python/pants/backend/rust/rules',
    ':target-types',
  ],
  tags={'partially_type_checked'},
)

python_library(
  name='target-types',
  sources=['target_types.py'],
  dependencies=[
    'src/python/pants/core',
    'src/python/pants/engine:target',
  ],
  tags={'partially_type_checked'},
)
