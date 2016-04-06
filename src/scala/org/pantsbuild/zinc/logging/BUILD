scala_library(
  name='logging',
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-logging',
    repo=public,
    publication_metadata=pants_library('The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '3rdparty/jvm/org/scala-sbt:incrementalcompiler',
    '3rdparty/jvm/org/scala-sbt:util-logging',
  ],
  sources=globs('*.scala'),
  strict_deps=True,
)
