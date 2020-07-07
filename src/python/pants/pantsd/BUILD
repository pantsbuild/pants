# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pants_daemon_client',
  sources = ['pants_daemon_client.py'],
  dependencies = [
    ':pants_daemon',
    ':process_manager',
    '3rdparty/python:dataclasses',
    'src/python/pants/option',
  ],
)

python_library(
  name = 'pants_daemon_core',
  sources = ['pants_daemon_core.py'],
  dependencies = [
    '3rdparty/python:typing-extensions',
    'src/python/pants/init',
    'src/python/pants/init:engine_initializer',
    'src/python/pants/option',
    'src/python/pants/option:options_bootstrapper',
    'src/python/pants/pantsd/service:pants_service',
  ],
)

python_library(
  name = 'pants_daemon',
  sources = ['pants_daemon.py'],
  dependencies = [
    ':pants_daemon_core',
    ':process_manager',
    '3rdparty/python:setproctitle',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exception_sink',
    'src/python/pants/bin:daemon_pants_runner',
    'src/python/pants/engine/internals:native',
    'src/python/pants/init',
    'src/python/pants/init:engine_initializer',
    'src/python/pants/option',
    'src/python/pants/option:options_bootstrapper',
    'src/python/pants/pantsd/service:scheduler_service',
    'src/python/pants/pantsd/service:store_gc_service',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:logging',
    'src/python/pants/util:strutil',
  ],
)

python_library(
  name = 'process_manager',
  sources = ['process_manager.py'],
  dependencies = [
    '3rdparty/python:psutil',
    'src/python/pants/base:build_environment',
    'src/python/pants/option',
    'src/python/pants/process',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
)
