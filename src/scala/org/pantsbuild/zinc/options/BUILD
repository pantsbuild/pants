scala_library(
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-options',
    repo=public,
    publication_metadata=pants_library('The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '3rdparty/jvm/org/scala-lang/modules:scala-java8-compat',
    '3rdparty/jvm/org/scala-sbt:zinc',
  ],
  strict_deps=True,
  platform='java8',
)
