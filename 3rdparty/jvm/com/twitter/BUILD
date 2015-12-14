# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(name='finagle-thrift',
  jars=[
    scala_jar(org='com.twitter', name='finagle-thrift', rev='6.28.0',
        excludes=[
          exclude(org = 'org.apache.thrift', name = 'libthrift'),
        ]),
  ],
  dependencies=[
    '3rdparty:thrift-0.6.1',
  ],
)

jar_library(name='scrooge-core',
  jars=[
    scala_jar(org='com.twitter', name='scrooge-core', rev='3.20.0',
        excludes=[
          exclude(org = 'org.apache.thrift', name = 'libthrift'),
        ]),
  ],
  dependencies=[
    '3rdparty:thrift-0.6.1',
  ],
)
