python_library(
  name = 'goal',
  sources = ['__init__.py'],
  dependencies = [
    pants(':error'),
    pants(':context'),
    pants(':group'),
    pants(':phase'),
    pants(':run_tracker'),
    pants('src/python/twitter/pants/base:build_manual'),
    pants('src/python/twitter/pants/tasks:task'),
  ],
)

python_library(
  name = 'aggregated_timings',
  sources = ['aggregated_timings.py'],
  dependencies = [
    pants('src/python/twitter/common/dirutil'),
  ]
)

# why is this in goal?
python_library(
  name = 'artifact_cache_stats',
  sources = ['artifact_cache_stats.py'],
  dependencies = [
    pants('src/python/twitter/common/dirutil'),
  ]
)

python_library(
  name = 'context',
  sources = ['context.py'],
  dependencies = [
    pants(':products'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/process'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/base:workunit'),
    pants('src/python/twitter/pants/java:distribution'),  # XXX(fixme)
    pants('src/python/twitter/pants/reporting'),
    pants('src/python/twitter/pants/targets:all'),  # XXX(fixme)
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
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/pants/reporting'),
  ],
)

python_library(
  name = 'phase',
  sources = ['phase.py'],
  dependencies = [
    pants(':error'),
    pants('src/python/twitter/pants/base:build_manual'),
  ],
)

python_library(
  name = 'products',
  sources = ['products.py'],
  dependencies = [
    pants('src/python/twitter/common/collections'),
  ],
)

python_library(
  name = 'run_tracker',
  sources = ['run_tracker.py'],
  dependencies = [
    pants(':aggregated_timings'),
    pants(':artifact_cache_stats'),
    pants('src/python/twitter/pants/base:run_info'),
    pants('src/python/twitter/pants/base:worker_pool'),
    pants('src/python/twitter/pants/base:workunit'),
    pants('src/python/twitter/pants/reporting'),
    pants('src/python/twitter/pants/base:config'),
  ],
)

