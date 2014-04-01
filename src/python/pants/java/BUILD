# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'distribution',
  sources = globs('distribution/*.py'),
  resources = globs('distribution/*.class'),
  dependencies = [
    pants('src/python/pants/BUILD.commons:twitter.common.contextutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.lang'),
    pants('src/python/pants/BUILD.commons:twitter.common.log'),
    pants('src/python/pants/base:revision'),
  ]
)

python_library(
  name = 'executor',
  sources = ['executor.py'],
  dependencies = [
    pants(':distribution'),
    pants('src/python/pants/BUILD.commons:twitter.common.collections'),
    pants('src/python/pants/BUILD.commons:twitter.common.contextutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.lang'),
    pants('src/python/pants/BUILD.commons:twitter.common.log'),
  ]
)

python_library(
  name = 'jar',
  sources = globs('jar/*.py'),
  dependencies = [
    pants('src/python/pants/BUILD.commons:twitter.common.contextutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.lang'),
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
    pants('src/python/pants/BUILD.commons:twitter.common.collections'),
    pants('src/python/pants/BUILD.commons:twitter.common.dirutil'),
    pants('src/python/pants/BUILD.commons:twitter.common.lang'),
    pants('src/python/pants/BUILD.commons:twitter.common.log'),
    pants('src/python/pants/base:build_environment'),
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
