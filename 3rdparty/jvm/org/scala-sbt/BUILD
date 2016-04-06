jar_library(
  name='incrementalcompiler',
  jars=[
    scala_jar(org='org.scala-sbt', name='incrementalcompiler', rev='0.1.0-M3', excludes =[
      exclude(org='org.scala-sbt', name='io_2.10'),
      exclude(org='org.scala-sbt', name='util-logging_2.10'),
    ])
  ],
)

jar_library(
  name='util-logging',
  jars=[
    # TODO: `incrementalcompiler` only declares a dep on the `tests` classifier for
    # util-logging for some reason. We redefine the dep here to get the full package.
    scala_jar(org='org.scala-sbt', name='util-logging', rev='0.1.0-M8', force=True),
  ],
)

jar_library(
  name='io',
  jars=[
    # TODO: `incrementalcompiler` only declares a dep on the `tests` classifier for
    # io. We redefine the dep here to get the full package.
    scala_jar(org='org.scala-sbt', name='io', rev='1.0.0-M3', force=True),
  ],
)
