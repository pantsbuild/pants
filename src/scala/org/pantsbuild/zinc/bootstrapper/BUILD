# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-bootstrapper',
    repo=public,
    publication_metadata=pants_library('Bootstrapper for The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '3rdparty/jvm/org/scala-sbt:zinc',
    '3rdparty/jvm/org/scala-sbt:util-logging',
    '3rdparty/jvm/org/scala-sbt:io',
    '3rdparty/jvm/com/github/scopt',
    '3rdparty/jvm/org/pantsbuild/buck/util/zip',
    'src/scala/org/pantsbuild/zinc/options',
    'src/scala/org/pantsbuild/zinc/scalautil',
  ],
  platform='java8',
)
