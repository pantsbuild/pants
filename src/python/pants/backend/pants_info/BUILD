# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/backend/graph_info/subsystems',
    'src/python/pants/base:build_root',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:console',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:goal',
    'src/python/pants/engine:platform',
    'src/python/pants/engine:process',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/option',
    'src/python/pants/source',
    'src/python/pants/util:objects',
  ],
  tags = {"type_checked"},
)

python_tests(
  name = "tests",
  dependencies = [
    ':pants_info',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:target',
    'src/python/pants/engine:unions',
    'src/python/pants/option',
    'src/python/pants/source',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"type_checked"},
)
