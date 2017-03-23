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
