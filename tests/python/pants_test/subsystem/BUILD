# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='subsystem',
  sources=['test_subsystem.py', 'test_subsystem_client_mixin.py'],
  dependencies=[
    '3rdparty/python:mock',
    '3rdparty/python:pytest',
    'src/python/pants/option',
    'src/python/pants/subsystem',
  ],
)

python_library(
  name='subsystem_utils',
  sources=['subsystem_util.py'],
  dependencies=[
    'src/python/pants/subsystem',
    'tests/python/pants_test/option/util',
  ],
)
