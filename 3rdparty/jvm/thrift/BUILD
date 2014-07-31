# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
  name = 'libthrift-0.5.0',
  jars = [
    jar(org='org.apache.thrift', name='libthrift', rev='0.5.0-1'),
  ],
)

jar_library(
  name = 'thrift-0.5.0',
  dependencies = [
    ':libthrift-0.5.0',
    '3rdparty/jvm/commons:commons-lang',
    '3rdparty/jvm/slf4j:slf4j-api',
  ],
)

jar_library(
  name = 'thrift-0.5.0-finagle',
  dependencies = [
    ':thrift-0.5.0',

    # finagle thrift extra deps
    '3rdparty/jvm/finagle:finagle-core',
    '3rdparty/jvm/finagle:finagle-thrift',
    '3rdparty/jvm/util:util-core',
  ],
)

jar_library(
  name = 'thrift',
  dependencies = [
    ':thrift-0.5.0',
  ],
)
