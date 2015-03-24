# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'tasks',
  dependencies = [
    ':scrooge_gen',
    ':thrift_linter',
  ],
)

python_library(
  name = 'scrooge_gen',
  sources = ['scrooge_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants:pants-packaged',
  ],
)

python_library(
  name = 'thrift_linter',
  sources = ['thrift_linter.py'],
  dependencies = [
    'src/python/pants:pants-packaged',
  ],
)
