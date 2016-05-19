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
    "src/python/pants/base:revision"
  ]
)

page(name='changelog',
  source='CHANGELOG.md',
  links=[
    'src/python/pants/notes:notes-1.0.x',
    'src/python/pants/notes:notes-master',
  ],
  description='''
This file is no longer a changelog, but remains in this location in order to avoid breaking
older changelog links unnecessarily. Could consider removing it by 2.0.x, perhaps.
''',
)
