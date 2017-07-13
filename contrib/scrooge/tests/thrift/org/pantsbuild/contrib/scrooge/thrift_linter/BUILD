# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_thrift_library(
  name = 'error-default',
  sources = ['error.thrift'],
  # thrift_linter_strict not defined
)

java_thrift_library(
  name = 'error-strict',
  sources = ['error.thrift'],
  thrift_linter_strict=True,
)

java_thrift_library(
  name = 'error2-strict',
  sources = ['error2.thrift'],
  thrift_linter_strict=True,
)

java_thrift_library(
  name = 'error-non-strict',
  sources = ['error.thrift'],
  thrift_linter_strict=False,
)

java_thrift_library(
  name = 'good',
  sources = ['good.thrift'],
  thrift_linter_strict=True,
)

java_thrift_library(
  name = 'warn',
  sources = ['warn.thrift'],
  thrift_linter_strict=False,
)
