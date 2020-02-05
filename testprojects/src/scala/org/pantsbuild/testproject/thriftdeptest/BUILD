# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
  dependencies = [
    'testprojects/src/thrift/org/pantsbuild/testproject:thrift-java',
  ],
  sources = ['**/*.scala'],
  # NB: this setting is a temporary way to get tests passing, as Scrooge and Thrift
  # require JDK 8 to function properly. This constraint should really be specified in
  # source code, not in test BUILD files. See #6956
  platform='java8',
)
