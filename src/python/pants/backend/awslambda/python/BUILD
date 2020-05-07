# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/awslambda/common',
    'src/python/pants/build_graph',
    'src/python/pants/core/util_rules',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/python',
  ],
  tags = {"type_checked"},
)

python_tests(
  name='tests',
  dependencies=[
    ':python',
    'src/python/pants/backend/python/rules',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/awslambda/common',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/source',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil:external_tool_test_base',
    'src/python/pants/testutil/option',
  ],
  tags = {'partially_type_checked'},
)
