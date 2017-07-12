jar_library(
  name='zinc',
  jars=[
    # TODO: When this is bumped beyond -M1, the scalacenter resolver should be removed
    # from `build-support/ivy/ivysettings.xml`.
    scala_jar(org='org.scala-sbt', name='zinc', rev='1.0.0-X19-M1',
              excludes=[
                exclude(org='org.scala-sbt', name='io_2.11'),
                exclude(org='org.scala-sbt', name='util-logging_2.11'),
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
    scala_jar(org='org.scala-sbt', name='util-logging', rev='1.0.0-M24', force=True),
  ],
)

jar_library(
  name='io',
  jars=[
    # TODO: `zinc` only declares a dep on the `tests` classifier for
    # io. We redefine the dep here to get the full package.
    scala_jar(org='org.scala-sbt', name='io', rev='1.0.0-M10', force=True),
  ],
)
