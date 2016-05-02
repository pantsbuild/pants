# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pants_service',
  sources = ['pants_service.py'],
  dependencies = [
    'src/python/pants/util:meta',
  ],
)

python_library(
  name = 'fs_event_service',
  sources = ['fs_event_service.py'],
  dependencies = [
    '3rdparty/python:futures',
    ':pants_service',
    'src/python/pants/pantsd:watchman',
  ],
)

python_library(
  name = 'pailgun_service',
  sources = ['pailgun_service.py'],
  dependencies = [
    ':pants_service',
    'src/python/pants/pantsd:pailgun_server',
  ],
)

python_library(
  name = 'scheduler_service',
  sources = ['scheduler_service.py'],
  dependencies = [
    ':pants_service',
  ],
)
