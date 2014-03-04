python_library(
  name = 'analysis',
  sources = ['analysis.py'],
)

python_library(
  name = 'analysis_parser',
  sources = ['analysis_parser.py'],
  dependencies = [
    pants('src/python/twitter/pants/tasks:task_error'),
  ]
)

python_library(
  name = 'analysis_tools',
  sources = ['analysis_tools.py'],
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/pants/base:build_environment'),
  ]
)

python_library(
  name = 'java',
  sources = globs('java/*.py'),
  dependencies = [
    pants(':analysis'),
    pants(':analysis_tools'),
    pants(':jvm_compile'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/base:workunit'),
    pants('src/python/twitter/pants/tasks:task_error'),
  ],
)

python_library(
  name = 'jvm_compile',
  sources = ['jvm_compile.py'],
  dependencies = [
    pants(':jvm_dependency_analyzer'),
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/base:worker_pool'),
    pants('src/python/twitter/pants/goal:products'),
    pants('src/python/twitter/pants/reporting'),
    pants('src/python/twitter/pants/tasks:nailgun_task'),
    pants('src/python/twitter/pants/tasks:task'),
  ],
)

python_library(
  name = 'jvm_dependency_analyzer',
  sources = ['jvm_dependency_analyzer.py'],
  dependencies = [
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/targets:jvm'),
    pants('src/python/twitter/pants/tasks:common'),
  ],
)

python_library(
  name = 'scala',
  sources = globs('scala/*.py'),
  dependencies = [
    pants(':analysis'),
    pants(':analysis_parser'),
    pants(':analysis_tools'),
    pants(':jvm_compile'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:hash_utils'),
    pants('src/python/twitter/pants/base:workunit'),
    pants('src/python/twitter/pants/targets:scala'),
    pants('src/python/twitter/pants/tasks:task_error'),
  ],
)
