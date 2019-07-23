scala_library(
  provides=scala_artifact(
      org='org.pantsbuild',
      name='scoverage-report-generator',
      repo=public,
      publication_metadata=pants_library('Report Generator for scoverage.')
    ),
    dependencies = [
    '3rdparty/jvm/commons-io',
    '3rdparty/jvm/com/github/scopt',
    '3rdparty/jvm/com/twitter/scoverage:scalac-scoverage-plugin',
    '3rdparty/jvm/org/slf4j:slf4j-simple',
    '3rdparty/jvm/org/slf4j:slf4j-api'
    ],
)
