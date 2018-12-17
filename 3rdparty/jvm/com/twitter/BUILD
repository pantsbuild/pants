# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

SCROOGE_REV = '18.12.0'

# NB: The scrooge tools do not mix their classpaths with the sources they interact with, and
# therefore they do not need to use the `scala-platform` via scala_jar.
jar_library(name = 'scrooge-gen',
            jars = [
              jar(org='com.twitter', name='scrooge-generator_2.11', rev=SCROOGE_REV)
            ])

jar_library(name = 'scrooge-linter',
            jars = [
              jar(org='com.twitter', name='scrooge-linter_2.11', rev=SCROOGE_REV)
            ])

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
