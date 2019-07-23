# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

SCROOGE_REV = '18.12.0'

jar_library(name='finagle-thrift',
  jars=[
    scala_jar(org='com.twitter', name='finagle-thrift', rev=SCROOGE_REV),
  ],
)

jar_library(name='scrooge-core',
  jars=[
    scala_jar(org='com.twitter', name='scrooge-core', rev=SCROOGE_REV),
  ],
)

jar_library(name='scalac-scoverage-plugin',
  jars=[
    scala_jar(org='com.twitter.scoverage', name='scalac-scoverage-plugin', rev='1.0.1-twitter'),
    ],
  )
