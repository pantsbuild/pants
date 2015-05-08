scala_library(name='zinc',
  provides=artifact(
    org='org.pantsbuild',
    name='zinc',
    repo=public,
    publication_metadata=pants_library('The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '//:nailgun-server',
    '3rdparty/jvm/com/typesafe/sbt:compiler-interface',
    '3rdparty/jvm/com/typesafe/sbt:incremental-compiler',
    '3rdparty/jvm/com/typesafe/sbt:sbt-interface',
    '3rdparty:guava',
  ],
  sources=globs('*.scala'),
)
