# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'plugins',
  dependencies = [
    'contrib/confluence/src/python/pants/contrib/confluence:plugin',
    'contrib/go/src/python/pants/contrib/go:plugin',
    'contrib/mypy/src/python/pants/contrib/mypy:plugin',
    'contrib/node/src/python/pants/contrib/node:plugin',
    'contrib/scrooge/src/python/pants/contrib/scrooge:plugin',
  ]
)

files(
  name = 'isort_cfg',
  sources = ['.isort.cfg'],
)
