# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-extractor',
    repo=public,
    publication_metadata=pants_library('The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '3rdparty/jvm/com/fasterxml/jackson/module:scala',
    '3rdparty/jvm/org/scala-lang/modules:scala-java8-compat',
    '3rdparty/jvm/org/scala-sbt:zinc',
    'src/scala/org/pantsbuild/zinc/analysis',
    'src/scala/org/pantsbuild/zinc/options',
  ],
  strict_deps=True,
  platform='java8',
)
