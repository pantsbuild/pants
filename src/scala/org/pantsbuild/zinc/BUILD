scala_library(
  name='zinc',
  provides=artifact(
    org='org.pantsbuild',
    name='zinc',
    repo=public,
    publication_metadata=pants_library('The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '3rdparty/jvm/com/typesafe/sbt:incremental-compiler',
    'src/scala/org/pantsbuild/zinc/cache',
    'src/scala/org/pantsbuild/zinc/logging',
    'src/scala/sbt/inc',
    'src/scala/sbt/compiler/javac',
  ],
  sources=globs('*.scala'),
)
