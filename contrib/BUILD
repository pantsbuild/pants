# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'plugins',
  dependencies = [
    'contrib/awslambda/python/src/python/pants/contrib/awslambda/python:plugin',
    'contrib/buildrefactor/src/python/pants/contrib/buildrefactor:plugin',
    'contrib/codeanalysis/src/python/pants/contrib/codeanalysis:plugin',
    'contrib/confluence/src/python/pants/contrib/confluence:plugin',
    'contrib/go/src/python/pants/contrib/go:plugin',
    'contrib/mypy/src/python/pants/contrib/mypy:plugin',
    'contrib/node/src/python/pants/contrib/node:plugin',
    'contrib/python/src/python/pants/contrib/python/checks:plugin',
    'contrib/scrooge/src/python/pants/contrib/scrooge:plugin',
  ]
)

files(
  name = 'isort_cfg',
  sources = ['.isort.cfg'],
)
