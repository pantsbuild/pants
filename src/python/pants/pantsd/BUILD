# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'process_manager',
  sources = ['process_manager.py'],
  dependencies = [
    '3rdparty/python:psutil',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'pailgun_server',
  sources = ['pailgun_server.py'],
  dependencies = [
    '3rdparty/python:six',
    'src/python/pants/java:nailgun_protocol',
    'src/python/pants/util:socket',
  ],
)

python_library(
  name = 'watchman',
  sources = ['watchman.py'],
  dependencies = [
    ':process_manager',
    ':watchman_client',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:retry',
  ],
)

python_library(
  name = 'watchman_client',
  sources = ['watchman_client.py'],
  dependencies = [
    '3rdparty/python:pywatchman',
  ],
)

python_library(
  name = 'pants_daemon',
  sources = ['pants_daemon.py'],
  dependencies = [
    '3rdparty/python:setproctitle',
    ':process_manager',
    'src/python/pants/goal',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/logging',
  ],
)
