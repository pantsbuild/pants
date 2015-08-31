# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'test_deps',
  dependencies = [
    '3rdparty/python:mock',
    '3rdparty/python:pytest',
    'tests/python/pants_test:base_test'
  ]
)

python_tests(
  name = 'process_manager',
  sources = ['test_process_manager.py'],
  coverage = ['pants.pantsd.process_manager'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:process_manager'
  ]
)

python_tests(
  name = 'watchman',
  sources = ['test_watchman.py'],
  coverage = ['pants.pantsd.watchman'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:watchman'
  ]
)

python_tests(
  name = 'watchman_client',
  sources = ['test_watchman_client.py'],
  coverage = ['pants.pantsd.watchman_client'],
  dependencies = [
    ':test_deps',
    'src/python/pants/pantsd:watchman_client'
  ]
)
