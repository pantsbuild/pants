scala_library(
  name='inc',
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-sbt-inc',
    repo=public,
    publication_metadata=pants_library('Temporary shims to expose accidentally-private SBT apis.')
  ),
  dependencies=[
    '3rdparty/jvm/com/typesafe/sbt:incremental-compiler',
  ],
  sources=globs('*.scala'),
)
