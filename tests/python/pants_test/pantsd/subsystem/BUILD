# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'watchman_launcher',
  sources = ['test_watchman_launcher.py'],
  coverage = ['pants.pantsd.subsystem.watchman_launcher'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/pantsd/subsystem:watchman_launcher',
    'src/python/pants/pantsd:watchman',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'pants_daemon_launcher',
  sources = ['test_pants_daemon_launcher.py'],
  coverage = ['pants.pantsd.subsystem.pants_daemon_launcher'],
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/pantsd/subsystem:pants_daemon_launcher',
    'src/python/pants/pantsd:pants_daemon',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:base_test',
  ],
)
