# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all',
  dependencies = [
    ':process_manager',
  ]
)

python_tests(
  name = 'process_manager',
  sources = ['test_process_manager.py'],
  coverage = ['pants.pantsd.process_manager'],
  dependencies = [
    'src/python/pants/pantsd:process_manager',
    'tests/python/pants_test:base_test',
    # 'src/python/pants/util:contextutil',
    # 'src/python/pants/util:fileutil',
    '3rdparty/python:mock',
    '3rdparty/python:pytest',
  ]
)
