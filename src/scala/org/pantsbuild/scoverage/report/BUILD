scala_library(
    dependencies = [
    '3rdparty/jvm/commons-io',
    '3rdparty/jvm/org/scala-sbt:util-logging',
    'src/scala/org/pantsbuild/zinc/options',
    ],
)

jvm_binary(
  name = "gen2",
  basename = "gen2",
  main = "org.pantsbuild.scoverage.report.ScoverageRep",
   dependencies=[
      ":report",
    ]
)
