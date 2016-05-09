# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['__init__.py', 'register.py'],
  dependencies = [
    'src/python/pants/backend/jvm:ossrh_publication_metadata',
    'src/python/pants/backend/jvm:repository',
    'src/python/pants/build_graph',
  ],
)

