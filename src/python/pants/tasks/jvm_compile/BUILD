# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'analysis',
  sources = ['analysis.py'],
)

python_library(
  name = 'analysis_parser',
  sources = ['analysis_parser.py'],
  dependencies = [
    pants('src/python/pants/tasks:task_error'),
  ]
)

python_library(
  name = 'analysis_tools',
  sources = ['analysis_tools.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('src/python/pants/base:build_environment'),
  ]
)

python_library(
  name = 'java',
  sources = globs('java/*.py'),
  dependencies = [
    pants(':analysis'),
    pants(':analysis_tools'),
    pants(':jvm_compile'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/tasks:task_error'),
  ],
)

python_library(
  name = 'jvm_compile',
  sources = ['jvm_compile.py'],
  dependencies = [
    pants(':jvm_dependency_analyzer'),
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:worker_pool'),
    pants('src/python/pants/goal:products'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/tasks:nailgun_task'),
    pants('src/python/pants/tasks:task'),
  ],
)

python_library(
  name = 'jvm_dependency_analyzer',
  sources = ['jvm_dependency_analyzer.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.collections'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/targets:jvm'),
    pants('src/python/pants/tasks:common'),
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
    pants('3rdparty/python:twitter.common.collections'),
    pants('3rdparty/python:twitter.common.contextutil'),
    pants('3rdparty/python:twitter.common.dirutil'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:hash_utils'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/targets:scala'),
    pants('src/python/pants/tasks:task_error'),
  ],
)
