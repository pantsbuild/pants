python_library(
  name = 'python',
  sources = globs('*.py'),
  dependencies = [
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/pants/base:parse_context'),
    pants('src/python/twitter/pants/base:target'),
    pants('src/python/twitter/pants/python:interpreter_cache'),
    pants('src/python/twitter/pants/targets:python'),
    pants('src/python/twitter/pants/tasks:common'),
  ]
)
