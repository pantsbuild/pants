# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources = ['source_root.py', 'wrapped_globs.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python:dataclasses',
    '3rdparty/python:typing-extensions',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:parse_context',
    'src/python/pants/engine:collection',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = "filespec",
  sources = ["filespec.py"],
  dependencies = [
    ':source',
    'src/python/pants/engine/internals:native',
    'src/python/pants/engine:fs',
  ],
  tags = {"type_checked"},
)

python_library(
  name = 'payload_fields',
  sources = ['payload_fields.py'],
  dependencies = [
    ':filespec',
    ':source',
    'src/python/pants/base:payload_field',
    'src/python/pants/engine/internals:scheduler',
    'src/python/pants/engine:fs',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'tests',
  dependencies = [
    ':source',
    ':payload_fields',
    'src/python/pants/base:payload',
    'src/python/pants/build_graph',
    'src/python/pants/engine:fs',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/engine:util',
  ],
  tags = {"partially_type_checked"},
)
