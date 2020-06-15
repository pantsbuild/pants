# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=["*.py", "!address.py", "!bundle.py", "!bundle_mixin.py", "!*_test.py"],
  dependencies = [
    ':address',
    ':bundle',
    '3rdparty/python:dataclasses',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_target_factory',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:fingerprint_strategy',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:parse_context',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:specs',
    'src/python/pants/base:validation',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:target',
    'src/python/pants/fs',
    'src/python/pants/option',
    'src/python/pants/source',
    'src/python/pants/source:payload_fields',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:frozendict',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
    'src/python/pants/util:netrc',
    'src/python/pants/util:objects',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name="address",
  sources=["address.py"],
  dependencies = [
    'src/python/pants/base:build_file',
    'src/python/pants/base:deprecated',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:strutil',
  ],
  tags = {"type_checked"},
)

python_library(
  name="bundle",
  sources=["bundle.py"],
  dependencies=[
    'src/python/pants/base:build_environment',
    'src/python/pants/base:payload_field',
    'src/python/pants/util:collections',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name="bundle_mixin",
  sources=["bundle_mixin.py"],
  dependencies=[
    ':build_graph',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/fs',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:fileutil',
  ],
  tags = {"partially_type_checked"},
)
