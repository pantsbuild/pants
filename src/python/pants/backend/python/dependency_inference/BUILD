# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    "3rdparty/python:dataclasses",
    "3rdparty/python:typed-ast",
    "src/python/pants/backend/python/dependency_inference/python_stdlib",
    "src/python/pants/backend/python:target_types",
    "src/python/pants/base:specs",
    "src/python/pants/core/util_rules",
    "src/python/pants/engine:fs",
    "src/python/pants/engine:rules",
    "src/python/pants/engine:target",
    "src/python/pants/engine:selectors",
    "src/python/pants/engine:unions",
    "src/python/pants/engine/internals:native",
    "src/python/pants/engine/legacy:structs",
    "src/python/pants/util:memo",
    "src/python/pants/util:ordered_set",
    "src/python/pants/util:strutil",
  ],
  tags = {"type_checked"},
)

python_tests(
  name="tests",
  dependencies=[
    ":dependency_inference",
    "src/python/pants/testutil:test_base",
  ],
  tags = {"type_checked"},
)
