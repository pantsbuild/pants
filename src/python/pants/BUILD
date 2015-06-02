# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='pants',
  dependencies=[
    'src/python/pants/bin:pants',
  ],
  description='An alias for the pants binary target.',
)

python_library(
  name='pants-packaged',
  provides=pants_setup_py(
    name='pantsbuild.pants',
    description='A bottom-up build tool.',
    namespace_packages=['pants', 'pants.backend'],
  ).with_binaries(
    pants='src/python/pants/bin:pants',
  )
)

page(name='readme',
  source='README.md',
)

# XXX move into base or thrift
python_library(
  name='binary_util',
  sources=['binary_util.py'],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:six',
    'src/python/pants/base:exceptions',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name='thrift_util',
  sources=['thrift_util.py'],
  dependencies=[
    ':binary_util',
  ],
)

python_library(
  name='version',
  sources=['version.py'],
)

page(
  name='changelog',
  source='CHANGELOG.rst'
)
