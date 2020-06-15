# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pants_daemon_client',
  sources = ['pants_daemon_client.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    ':pants_daemon',
    ':process_manager',
    'src/python/pants/option',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name = 'pants_daemon_core',
  sources = ['pants_daemon_core.py'],
  dependencies = [
    'src/python/pants/init',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name = 'pants_daemon',
  sources = ['pants_daemon.py'],
  dependencies = [
    '3rdparty/python:setproctitle',
    ':pants_daemon_core',
    ':process_manager',
    ':watchman_launcher',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exception_sink',
    'src/python/pants/base:exiter',
    'src/python/pants/binaries',
    'src/python/pants/engine/internals:native',
    'src/python/pants/engine:unions',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/init',
    'src/python/pants/option',
    'src/python/pants/option:options_bootstrapper',
    'src/python/pants/pantsd/service:fs_event_service',
    'src/python/pants/pantsd/service:scheduler_service',
    'src/python/pants/pantsd/service:store_gc_service',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:logging',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name = 'process_manager',
  sources = ['process_manager.py'],
  dependencies = [
    '3rdparty/python:psutil',
    'src/python/pants/base:build_environment',
    'src/python/pants/process',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
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
  name = 'watchman_client',
  sources = ['watchman_client.py'],
  dependencies = [
    '3rdparty/python:pywatchman'
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
