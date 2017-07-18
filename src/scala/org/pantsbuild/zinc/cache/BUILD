# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
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
  exports=[
    '3rdparty:guava',
  ],
  strict_deps=True,
  platform='java8',
)
