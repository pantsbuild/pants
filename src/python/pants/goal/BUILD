# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'goal',
  sources = ['__init__.py'],
  dependencies = [
    pants(':error'),
    pants(':context'),
    pants(':group'),
    pants(':phase'),
    pants(':run_tracker'),
    pants('src/python/pants/base:build_manual'),
    pants('src/python/pants/tasks:task'),
  ],
)

python_library(
  name = 'aggregated_timings',
  sources = ['aggregated_timings.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.dirutil'),
  ]
)

# why is this in goal?
python_library(
  name = 'artifact_cache_stats',
  sources = ['artifact_cache_stats.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.dirutil'),
  ]
)

python_library(
  name = 'context',
  sources = ['context.py'],
  dependencies = [
    pants(':products'),
    pants('3rdparty/python:twitter.common.collections'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('3rdparty/python:twitter.common.process'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/java:distribution'),  # XXX(fixme)
    pants('src/python/pants/reporting'),
    pants('src/python/pants/targets:all'),  # XXX(fixme)
  ],
)

python_library(
  name = 'error',
  sources = ['error.py'],
)

python_library(
  name = 'group',
  sources = ['group.py'],
)

python_library(
  name = 'initialize_reporting',  # XXX shouldn't this be in reporting?!
  sources = ['initialize_reporting.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('3rdparty/python:twitter.common.lang'),
    pants('src/python/pants/reporting'),
  ],
)

python_library(
  name = 'phase',
  sources = ['phase.py'],
  dependencies = [
    pants(':error'),
    pants('src/python/pants/base:build_manual'),
  ],
)

python_library(
  name = 'products',
  sources = ['products.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.collections'),
  ],
)

python_library(
  name = 'run_tracker',
  sources = ['run_tracker.py'],
  dependencies = [
    pants(':aggregated_timings'),
    pants(':artifact_cache_stats'),
    pants('src/python/pants/base:run_info'),
    pants('src/python/pants/base:worker_pool'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/base:config'),
  ],
)
