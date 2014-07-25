# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'goal',
  sources = ['goal.py'],
  dependencies = [
    pants(':error'),
    pants(':phase'),
    pants('src/python/pants/backend/core/tasks:task'),
  ],
)

python_library(
  name = 'aggregated_timings',
  sources = ['aggregated_timings.py'],
  dependencies = [
    pants('src/python/pants/util:dirutil'),
  ]
)

# why is this in goal?
python_library(
  name = 'artifact_cache_stats',
  sources = ['artifact_cache_stats.py'],
  dependencies = [
    pants('src/python/pants/util:dirutil'),
  ]
)

python_library(
  name = 'context',
  sources = ['context.py'],
  dependencies = [
    pants(':products'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.process'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:source_root'),
    pants('src/python/pants/base:target'), # XXX(fixme)
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/java:distribution'),  # XXX(fixme)
    pants('src/python/pants/reporting'),
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
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'option_helpers',
  sources = ['option_helpers.py'],
  dependencies = [
    pants('src/python/pants/base:config'),
  ],
)

python_library(
  name = 'phase',
  sources = ['phase.py'],
  dependencies = [
    pants(':error'),
  ],
)

python_library(
  name = 'products',
  sources = ['products.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
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
    pants('src/python/pants/reporting'), # XXX(fixme)
    pants('src/python/pants/base:config'),
  ],
)

