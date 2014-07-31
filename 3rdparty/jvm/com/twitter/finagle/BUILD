# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# common rev for all com.twitter%finagle* artifacts
FINAGLE_REV = '6.8.1'

jar_library(
  name='finagle-core',
  jars=[
    jar(org='com.twitter', name='finagle-core_2.9.2', rev=FINAGLE_REV).with_sources(),
  ],
  dependencies=[
    '3rdparty/jvm/com/twitter/util:util-core',
  ],
)

jar_library(
  name='finagle-thrift',
  jars=[
    jar(org='com.twitter', name='finagle-thrift_2.9.2', rev=FINAGLE_REV)
  ],
)
