# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python:dataclasses',
    'src/python/pants/backend/rust/subsystems',
    'src/python/pants/build_graph',
    'src/python/pants/core',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:console',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:goal',
    'src/python/pants/engine:process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/util:enums',
  ],
  tags={'partially_type_checked'},
)

python_tests(
  name='integration',
  sources=['*_integration_test.py'],
  dependencies=[
    'src/python/pants/backend/rust:plugin',
    'src/python/pants/backend/rust:target-types',
    ':rules',
    'src/python/pants/core/util_rules',
    'src/python/pants/testutil:goal_rule_test_base',
    'src/python/pants/testutil/engine:util',
  ],
  tags={'partially_type_checked', 'integration'},
)
