python_library(
  name = 'python',
  sources = globs('*.py'),
  dependencies = [
    '3rdparty/python:pex',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/core/tasks:common',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:target',
    'src/python/pants/base:workunit',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:strutil',
  ]
)
