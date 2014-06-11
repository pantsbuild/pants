python_library(
  name = 'python',
  sources = globs('*.py'),
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('3rdparty/python/twitter/commons:twitter.common.python'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/backend/python:interpreter_cache'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/backend/core/tasks:common'),
  ]
)
