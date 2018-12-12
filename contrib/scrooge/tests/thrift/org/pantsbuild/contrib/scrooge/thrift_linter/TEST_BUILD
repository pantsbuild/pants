# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_thrift_library(
  name = 'bad-thrift-default',
  sources = ['bad-default.thrift'],
  compiler = 'scrooge',
  tags=['nolint'],
  # thrift_linter_strict not defined
)

java_thrift_library(
  name = 'bad-thrift-strict',
  sources = ['bad-strict.thrift'],
  compiler = 'scrooge',
  thrift_linter_strict=True,
  tags=['nolint'],
)

java_thrift_library(
  name = 'bad-thrift-strict2',
  sources = ['bad-strict2.thrift'],
  compiler = 'scrooge',
  thrift_linter_strict=True,
  tags=['nolint'],
)

java_thrift_library(
  name = 'bad-thrift-non-strict',
  sources = ['bad-non-strict.thrift'],
  compiler = 'scrooge',
  thrift_linter_strict=False,
  tags=['nolint'],
)

java_thrift_library(
  name = 'good-thrift',
  sources = ['good.thrift'],
  compiler = 'scrooge',
  thrift_linter_strict=True,
  tags=['nolint'],
)
