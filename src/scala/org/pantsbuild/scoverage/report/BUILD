scala_library(
    dependencies = [
    '3rdparty/jvm/commons-io',
    '3rdparty/jvm/org/scala-sbt:util-logging',
    '3rdparty/jvm/com/github/scopt',
    '3rdparty/jvm/com/twitter:scalac-scoverage-plugin'
    ],
)

jvm_binary(
  name = "gen2",
  basename = "gen2",
  main = "org.pantsbuild.scoverage.report.ScoverageReport",
   dependencies=[
      ":report",
    ]
)
