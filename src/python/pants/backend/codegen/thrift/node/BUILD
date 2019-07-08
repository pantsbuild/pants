python_library(
  sources = globs('*.py')
  dependencies = [
    'contrib/node/src/python/pants/contrib/node/targets:node_modules',
    'contrib/node/src/python/pants/contrib/node/targets:node_thrift_library',
    'src/python/pants/backend/codegen/thrift/lib',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/task',
  ],
)