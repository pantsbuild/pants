# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
  name='libthrift-0.5.0',
  jars=[
    jar(org='org.apache.thrift', name='libthrift', rev='0.5.0-1'),
  ],
)

jar_library(
  name='thrift-0.5.0',
  dependencies=[
    '3rdparty/jvm/commons-lang',
    '3rdparty/jvm/org/slf4j:slf4j-api',
    ':libthrift-0.5.0',
  ],
)

jar_library(
  name='thrift-0.5.0-finagle',
  dependencies=[
    # finagle thrift extra deps
    '3rdparty/jvm/com/twitter/finagle:finagle-core',
    '3rdparty/jvm/com/twitter/finagle:finagle-thrift',
    '3rdparty/jvm/com/twitter/util:util-core',

    ':thrift-0.5.0',
  ],
)

jar_library(
  name='thrift',
  dependencies=[
    ':thrift-0.5.0',
  ],
)
