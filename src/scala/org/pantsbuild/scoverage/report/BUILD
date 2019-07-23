scala_library(
  provides=scala_artifact(
      org='org.pantsbuild',
      name='scoverageReport',
      repo=public,
      publication_metadata=pants_library('Report Generator for scoverage.')
    ),
    dependencies = [
    '3rdparty/jvm/commons-io',
    '3rdparty/jvm/org/scala-sbt:util-logging',
    '3rdparty/jvm/com/github/scopt',
    '3rdparty/jvm/com/twitter:scalac-scoverage-plugin'
    ],
)
