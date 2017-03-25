jar_library(
  name='zinc',
  jars=[
    scala_jar(org='org.scala-sbt', name='zinc', rev='1.0.0-X7',
              excludes=[
                exclude(org='org.scala-sbt', name='io_2.11'),
                exclude(org='org.scala-sbt', name='util-logging_2.11'),
              ]),
  ],
)

jar_library(
  name='util-logging',
  jars=[
    # TODO: `zinc` only declares a dep on the `tests` classifier for
    # util-logging for some reason. We redefine the dep here to get the full package.
    scala_jar(org='org.scala-sbt', name='util-logging', rev='1.0.0-M17', force=True),
  ],
)

jar_library(
  name='io',
  jars=[
    # TODO: `zinc` only declares a dep on the `tests` classifier for
    # io. We redefine the dep here to get the full package.
    scala_jar(org='org.scala-sbt', name='io', rev='1.0.0-M9', force=True),
  ],
)
