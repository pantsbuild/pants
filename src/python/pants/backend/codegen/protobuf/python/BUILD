# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    'src/python/pants/backend/codegen/protobuf',
    'src/python/pants/backend/codegen/protobuf/subsystems',
    'src/python/pants/backend/python:target_types',
    'src/python/pants/build_graph',
    'src/python/pants/core/util_rules',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:platform',
    'src/python/pants/engine:process',
    'src/python/pants/engine:target',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:unions',
  ],
  tags = {"type_checked"},
)

python_tests(
  name="tests",
  dependencies = [
    ':python',
    'src/python/pants/backend/codegen/protobuf',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:target',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/option',
  ],
  tags = {"type_checked"},
)
