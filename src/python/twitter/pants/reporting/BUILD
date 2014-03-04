python_library(
  name = 'reporting',
  sources = globs('*.py'),
  resources = rglobs('assets/*') + globs('templates/*.mustache'),
  dependencies = [
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/threading'),
    pants('src/python/twitter/pants/base:build_environment'),
    pants('src/python/twitter/pants/base:build_file'),
    pants('src/python/twitter/pants/base:mustache'),
    pants('src/python/twitter/pants/base:workunit'),
    pants('src/python/twitter/pants/goal:run_tracker'),  # XXX
    pants('3rdparty/python:ansicolors'),
    pants('3rdparty/python:pystache'),
  ]
)
