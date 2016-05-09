# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'scm',
  sources = ['scm.py'],
  dependencies = [
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
