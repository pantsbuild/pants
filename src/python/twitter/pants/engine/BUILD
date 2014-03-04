python_library(
  name = 'engine',
  sources = globs('*.py'),
  dependencies = [
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/pants/base:workunit'),
    pants('src/python/twitter/pants/goal'),
    pants('src/python/twitter/pants/targets:common'),
    pants('src/python/twitter/pants/tasks:check_exclusives'),
    pants('src/python/twitter/pants/tasks:task_error'),
  ],
)
