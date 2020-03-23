# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: To build a native-image of zinc *for a specific scalac version*, the scala path
# (compiler,library,reflect) has to be provided to the native-image invocation with -cp! Also, graal
# needs to release 1.0.0rc15 with oracle/graal#1071 (a NullPointerException fix).
scala_library(
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-compiler',
    repo=public,
    publication_metadata=pants_library('The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '3rdparty/jvm/com/github/scopt',
    '3rdparty/jvm/com/google/code/gson',
    '3rdparty/jvm/com/martiansoftware:nailgun-server',
    '3rdparty/jvm/org/eclipse/lsp4j',
    '3rdparty/jvm/org/scala-lang/modules:scala-java8-compat',
    '3rdparty/jvm/org/scala-sbt:io',
    '3rdparty/jvm/org/scala-sbt:util-logging',
    '3rdparty/jvm/org/scala-sbt:zinc',
    '3rdparty:guava',
    '3rdparty:jsr305',
    'src/scala/org/pantsbuild/zinc/analysis',
    'src/scala/org/pantsbuild/zinc/cache',
    'src/scala/org/pantsbuild/zinc/scalautil',
    'src/scala/org/pantsbuild/zinc/util',
    'src/scala/META-INF/native-image/org/pantsbuild/zinc/compiler:zinc-native-image-configuration',
    'src/scala/org/pantsbuild/zinc/compiler/native-image-substitutions',
    'src/scala/org/pantsbuild/zinc/compiler/native-image-substitutions:statics',
  ],
  strict_deps=True,
  platform='java8',
)
