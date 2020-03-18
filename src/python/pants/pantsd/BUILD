# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'process_manager',
  sources = ['process_manager.py'],
  dependencies = [
    '3rdparty/python:psutil',
    'src/python/pants/base:build_environment',
    'src/python/pants/process',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'pailgun_server',
  sources = ['pailgun_server.py'],
  dependencies = [
    'src/python/pants/java:nailgun_protocol',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:socket'
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'watchman',
  sources = ['watchman.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
    'src/python/pants/util:retry',
    ':process_manager',
    ':watchman_client'
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'watchman_launcher',
  sources = ['watchman_launcher.py'],
  dependencies = [
    ':watchman',
    'src/python/pants/binaries',
    'src/python/pants/util:logging',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'watchman_client',
  sources = ['watchman_client.py'],
  dependencies = [
    '3rdparty/python:pywatchman'
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'pants_daemon',
  sources = ['pants_daemon.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    '3rdparty/python:setproctitle',
    ':process_manager',
    ':watchman_launcher',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exception_sink',
    'src/python/pants/base:exiter',
    'src/python/pants/binaries',
    'src/python/pants/engine:native',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/init',
    'src/python/pants/pantsd/service:fs_event_service',
    'src/python/pants/pantsd/service:pailgun_service',
    'src/python/pants/pantsd/service:scheduler_service',
    'src/python/pants/pantsd/service:store_gc_service',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:logging',
    'src/python/pants/util:memo',
  ],
  tags = {'partially_type_checked'},
)
