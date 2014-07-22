# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    pants(':common'),
  ],
)

python_library(
  name = 'common',
  sources = [
    'dependencies.py',
    'doc.py',
    'resources.py',
  ],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:payload'),
    pants('src/python/pants/base:target'),
  ],
)
