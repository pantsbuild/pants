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

python_library(
  name='version',
  sources=['version.py'],
  dependencies = [
    'src/python/pants/base:revision',
  ],
)

page(
  name='changelog',
  source='CHANGELOG.rst'
)
