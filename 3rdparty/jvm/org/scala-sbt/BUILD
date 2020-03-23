# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

zinc_version = '1.1.7'

jar_library(
  name='zinc',
  jars=[
    scala_jar(org='org.scala-sbt', name='zinc', rev=zinc_version,
              excludes=[
                scala_exclude(org='org.scala-sbt', name='io'),
                scala_exclude(org='org.scala-sbt', name='util-logging'),
              ]),
  ],
  dependencies=[
    ':io',
    ':util-logging',
  ],
)

jar_library(
  name='util-logging',
  jars=[
    # TODO: `zinc` only declares a dep on the `tests` classifier for
    # util-logging for some reason. We redefine the dep here to get the full package.
    scala_jar(org='org.scala-sbt', name='util-logging', rev='1.1.3', force=True),
  ],
)

jar_library(
  name='io',
  jars=[
    # TODO: `zinc` only declares a dep on the `tests` classifier for
    # io. We redefine the dep here to get the full package.
    scala_jar(org='org.scala-sbt', name='io', rev='1.1.4', force=True),
  ],
)

jar_library(
  name='sbt-compiler-bridge',
  jars=[
    scala_jar(org='org.scala-sbt', name='compiler-bridge', rev=zinc_version),
  ],
)
