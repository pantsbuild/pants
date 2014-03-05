python_library(
  name = 'distribution',
  sources = globs('distribution/*.py'),
  resources = globs('distribution/*.class'),
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/log'),
    pants('src/python/twitter/pants/base:revision'),
  ]
)

python_library(
  name = 'executor',
  sources = ['executor.py'],
  dependencies = [
    pants(':distribution'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/log'),
  ]
)

python_library(
  name = 'jar',
  sources = globs('jar/*.py'),
  dependencies = [
    pants('src/python/twitter/common/contextutil'),
    pants('src/python/twitter/common/lang'),
  ]
)

python_library(
  name = 'nailgun_client',
  sources = ['nailgun_client.py'],
)

python_library(
  name = 'nailgun_executor',
  sources = ['nailgun_executor.py'],
  dependencies = [
    pants('3rdparty/python:psutil'),
    pants(':nailgun_client'),
    pants('src/python/twitter/common/collections'),
    pants('src/python/twitter/common/dirutil'),
    pants('src/python/twitter/common/lang'),
    pants('src/python/twitter/common/log'),
    pants('src/python/twitter/pants/base:build_environment'),
  ],
)

python_library(
  name = 'util',
  sources = ['util.py'],
  dependencies = [
    pants(':executor'),
    pants(':nailgun_executor'),
    pants('src/python/twitter/pants/base:workunit'),
  ],
)

