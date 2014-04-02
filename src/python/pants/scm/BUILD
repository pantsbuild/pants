# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    pants(':git'),
  ]
)

python_library(
  name = 'scm',
  sources = ['__init__.py'],
  dependencies = [
    pants('3rdparty/python:twitter.common.lang'),
  ],
)

python_library(
  name = 'git',
  sources = ['git.py'],
  dependencies = [
    pants(':scm'),
    pants('3rdparty/python:twitter.common.log'),
  ],
)
