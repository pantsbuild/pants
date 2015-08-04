# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all',
  dependencies = [
    ':process_manager',
    ':pants_daemon_launcher',
    ':watchman_launcher'
  ]
)

python_library(
  name = 'base_deps',
  dependencies = [
    '3rdparty/python:mock',
    '3rdparty/python:pytest',
    'src/python/pants/pantsd:pantsd',
    'tests/python/pants_test:base_test',
    'tests/python/pants_test/subsystem:subsystem_utils'
  ]
)

python_tests(
  name = 'process_manager',
  sources = ['test_process_manager.py'],
  coverage = ['pants.pantsd.process_manager'],
  dependencies = [':base_deps']
)

python_tests(
  name = 'pants_daemon_launcher',
  sources = ['subsystems/test_pants_daemon_launcher.py'],
  coverage = ['pants.pantsd.subsystems.pants_daemon_launcher'],
  dependencies = [':base_deps']
)

python_tests(
  name = 'watchman_launcher',
  sources = ['subsystems/test_watchman_launcher.py'],
  coverage = ['pants.pantsd.subsystems.watchman_launcher'],
  dependencies = [':base_deps']
)
