# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'plugins',
  dependencies = [
    'contrib/avro/src/python/pants/contrib/avro:plugin',
    'contrib/awslambda/python/src/python/pants/contrib/awslambda/python:plugin',
    'contrib/buildgen/src/python/pants/contrib/buildgen:plugin',
    'contrib/buildrefactor/src/python/pants/contrib/buildrefactor:plugin',
    'contrib/codeanalysis/src/python/pants/contrib/codeanalysis:plugin',
    'contrib/confluence/src/python/pants/contrib/confluence:plugin',
    'contrib/cpp/src/python/pants/contrib/cpp:plugin',
    'contrib/errorprone/src/python/pants/contrib/errorprone:plugin',
    'contrib/findbugs/src/python/pants/contrib/findbugs:plugin',
    'contrib/go/src/python/pants/contrib/go:plugin',
    'contrib/googlejavaformat/src/python/pants/contrib/googlejavaformat:plugin',
    'contrib/jax_ws/src/python/pants/contrib/jax_ws:plugin',
    'contrib/mypy/src/python/pants/contrib/mypy:plugin',
    'contrib/node/src/python/pants/contrib/node:plugin',
    'contrib/python/src/python/pants/contrib/python/checks:plugin',
    'contrib/scalajs/src/python/pants/contrib/scalajs:plugin',
    'contrib/scrooge/src/python/pants/contrib/scrooge:plugin',
    'contrib/thrifty/src/python/pants/contrib/thrifty:plugin',
  ]
)

files(
  name = 'isort_cfg',
  sources = ['.isort.cfg'],
)
