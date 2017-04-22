# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources = ['scm.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'src/python/pants/util:meta',
  ],
)

python_library(
  name = 'git',
  sources = ['git.py'],
  dependencies = [
    ':scm',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:memo',
    'src/python/pants/util:strutil',
  ],
)

python_library(
  name = 'change_calculator',
  sources = ['change_calculator.py'],
  dependencies = [
    'src/python/pants/base:specs',
    'src/python/pants/build_graph',
    'src/python/pants/goal:workspace',
  ],
)
