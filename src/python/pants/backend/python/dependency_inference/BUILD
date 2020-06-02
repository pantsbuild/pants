# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    "3rdparty/python:dataclasses",
    "3rdparty/python:typed-ast",
    "src/python/pants/util:ordered_set",
    "src/python/pants/util:strutil",
  ],
  tags = {"type_checked"},
)

python_tests(
  name="tests",
  dependencies=[
    ":dependency_inference",
  ],
  tags = {"type_checked"},
)
