scala_library(
  name='cache',
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-cache',
    repo=public,
    publication_metadata=pants_library('The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '3rdparty:guava',
    '3rdparty:jsr305',
  ],
  sources=globs('*.scala'),
  strict_deps=True,
)
