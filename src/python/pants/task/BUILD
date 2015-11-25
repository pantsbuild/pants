# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'task',
  sources = globs('*.py'),
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:fingerprint_strategy',
    'src/python/pants/base:worker_pool',
    'src/python/pants/cache',
    'src/python/pants/invalidation',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:meta',
  ],
)
