# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_thrift_library(
  name = 'good-thrift',
  sources = ['good.thrift'],
  compiler='scrooge',
  language='scala',
  rpc_style='finagle',
)

java_thrift_library(
  name = 'namespace-map-thrift',
  sources = ['good.thrift'],
  compiler='scrooge',
  language='scala',
  rpc_style='finagle',
  namespace_map = {
    'old': 'new',
  },
)

java_thrift_library(
  name = 'default-java-namespace-thrift',
  sources = ['good.thrift'],
  compiler='scrooge',
  language='scala',
  rpc_style='finagle',
  default_java_namespace = 'the_namespace',
)

java_thrift_library(
  name = 'include-paths-thrift',
  sources = ['good.thrift'],
  compiler='scrooge',
  language='scala',
  rpc_style='finagle',
  include_paths = [
    'some_dir',
  ],
)
