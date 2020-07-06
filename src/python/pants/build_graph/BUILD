# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=["*.py", "!address.py", "!*_test.py"],
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:parse_context',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:target',
    'src/python/pants/option',
    'src/python/pants/util:frozendict',
    'src/python/pants/util:meta',
    'src/python/pants/util:ordered_set',
  ],
)

python_library(
  name="address",
  sources=["address.py"],
  dependencies = [
    'src/python/pants/util:dirutil',
    'src/python/pants/util:strutil',
  ],
)
