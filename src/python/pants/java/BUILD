# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'distribution',
  sources = globs('distribution/*.py'),
  resources = globs('distribution/*.class'),
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('src/python/pants/base:revision'),
    pants('src/python/pants/util:contextutil'),
  ]
)

python_library(
  name = 'executor',
  sources = ['executor.py'],
  dependencies = [
    pants(':distribution'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/util:contextutil'),
  ]
)

python_library(
  name = 'jar',
  sources = globs('jar/manifest.py'),
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
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
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.log'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'util',
  sources = ['util.py'],
  dependencies = [
    pants(':executor'),
    pants(':nailgun_executor'),
    pants('src/python/pants/base:workunit'),
  ],
)
