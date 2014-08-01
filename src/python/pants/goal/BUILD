# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'goal',
  sources = ['goal.py'],
  dependencies = [
    ':error',
    ':phase',
    'src/python/pants/backend/core/tasks:task',
  ],
)

python_library(
  name = 'aggregated_timings',
  sources = ['aggregated_timings.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
  ]
)

# why is this in goal?
python_library(
  name = 'artifact_cache_stats',
  sources = ['artifact_cache_stats.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
  ]
)

python_library(
  name = 'context',
  sources = ['context.py'],
  dependencies = [
    ':products',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    '3rdparty/python/twitter/commons:twitter.common.process',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:source_root',
    'src/python/pants/base:target', # XXX(fixme)
    'src/python/pants/base:workunit',
    'src/python/pants/java:distribution',  # XXX(fixme)
    'src/python/pants/reporting',
  ],
)

python_library(
  name = 'error',
  sources = ['error.py'],
)

python_library(
  name = 'help',
  sources = ['help.py'],
  dependencies = [
    ':option_helpers',
    ':phase',
    'src/python/pants/base:build_environment',
  ],
)

python_library(
  name = 'initialize_reporting',  # XXX shouldn't this be in reporting?!
  sources = ['initialize_reporting.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.lang',
    'src/python/pants/reporting',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'option_helpers',
  sources = ['option_helpers.py'],
  dependencies = [
    'src/python/pants/base:config',
  ],
)

python_library(
  name = 'phase',
  sources = ['phase.py'],
  dependencies = [
    ':error',
  ],
)

python_library(
  name = 'products',
  sources = ['products.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
  ],
)

python_library(
  name = 'run_tracker',
  sources = ['run_tracker.py'],
  dependencies = [
    ':aggregated_timings',
    ':artifact_cache_stats',
    'src/python/pants/base:run_info',
    'src/python/pants/base:worker_pool',
    'src/python/pants/base:workunit',
    'src/python/pants/reporting', # XXX(fixme)
    'src/python/pants/base:config',
  ],
)

