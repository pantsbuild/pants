# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'engine_test_base',
  sources = ['base_engine_test.py'],
  dependencies = [
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)


python_library(
  name = 'util',
  sources = ['util.py'],
  dependencies = [
    '3rdparty/python:ansicolors',
    '3rdparty/python:dataclasses',
    'src/python/pants/engine/internals:core_abstractions',
    'src/python/pants/engine/internals:native',
    'src/python/pants/engine/internals:scheduler',
    'src/python/pants/engine:goal',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:unions',
    'src/python/pants/option',
    'src/python/pants/option:global_options',
    'src/python/pants/subsystem',
    'src/python/pants/util:objects',
  ],
  tags = {"partially_type_checked"},
)
