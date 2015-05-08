scala_library(name='zinc',
  provides=artifact(
    org='org.pantsbuild',
    name='zinc',
    repo=public,
    description="The SBT incremental compiler for nailgun"
  ),
  dependencies=[
      '//:nailgun-server',
      '3rdparty/jvm/com/typesafe/sbt:compiler-interface',
      '3rdparty/jvm/com/typesafe/sbt:incremental-compiler',
      '3rdparty/jvm/com/typesafe/sbt:sbt-interface',
  ],
  sources=globs('*.scala')
)
