# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    '3rdparty/python:dataclasses',
    '3rdparty/python:typing-extensions',
    'src/python/pants/base:build_root',
    'src/python/pants/base:specs',
    'src/python/pants/core',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:objects',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/fs',
    'src/python/pants/option',
    'src/python/pants/source',
    'src/python/pants/util:meta',
  ],
  tags = {"type_checked"},
)

python_tests(
  name = "tests",
  dependencies = [
    ':util_rules',
    'src/python/pants/base:specs',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:scheduler',
    'src/python/pants/engine:selectors',
    'src/python/pants/engine:target',
    'src/python/pants/testutil/option',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)
