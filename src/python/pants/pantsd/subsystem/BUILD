# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'subprocess',
  sources = ['subprocess.py'],
  dependencies = [
    'src/python/pants/option',
    'src/python/pants/subsystem',
  ]
)

python_library(
  name = 'watchman_launcher',
  sources = ['watchman_launcher.py'],
  dependencies = [
    ':subprocess',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/pantsd:watchman',
    'src/python/pants/subsystem:subsystem',
    'src/python/pants/util:memo',
  ]
)

python_library(
  name = 'pants_daemon_launcher',
  sources = ['pants_daemon_launcher.py'],
  dependencies = [
    ':subprocess',
    ':watchman_launcher',
    'src/python/pants/base:build_environment',
    'src/python/pants/pantsd/service:fs_event_service',
    'src/python/pants/pantsd/service:pailgun_service',
    'src/python/pants/pantsd/service:scheduler_service',
    'src/python/pants/pantsd:pants_daemon',
    'src/python/pants/process',
    'src/python/pants/subsystem:subsystem',
    'src/python/pants/util:memo',
  ]
)
