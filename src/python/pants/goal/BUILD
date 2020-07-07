# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'aggregated_timings',
  sources = ['aggregated_timings.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'pantsd_stats',
  sources = ['pantsd_stats.py'],
)

python_library(
  name = 'run_tracker',
  sources = ['run_tracker.py'],
  dependencies = [
    ':aggregated_timings',
    ':pantsd_stats',
    '3rdparty/python:requests',
    'src/python/pants/auth',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:run_info',
    'src/python/pants/base:worker_pool',
    'src/python/pants/base:workunit',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/subsystem',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
)
