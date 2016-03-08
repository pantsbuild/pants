# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'task',
  sources = globs('*.py'),
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:fingerprint_strategy',
    'src/python/pants/base:worker_pool',
    'src/python/pants/base:workunit',
    'src/python/pants/build_graph',
    'src/python/pants/cache',
    'src/python/pants/console:stty_utils',
    'src/python/pants/goal:workspace',
    'src/python/pants/invalidation',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/scm',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:meta',
    'src/python/pants/util:timeout',
  ],
)
