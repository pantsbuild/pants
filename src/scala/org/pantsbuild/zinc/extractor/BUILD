scala_library(
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-extractor',
    repo=public,
    publication_metadata=pants_library('The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '3rdparty/jvm/com/fasterxml/jackson/module:scala',
    '3rdparty/jvm/org/scala-sbt:zinc',
    'src/scala/org/pantsbuild/zinc/analysis',
    'src/scala/org/pantsbuild/zinc/options',
  ],
  strict_deps=True,
  platform='java8',
)
