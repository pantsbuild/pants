# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
  provides=scala_artifact(
    org='org.pantsbuild',
    name='zinc-compiler',
    repo=public,
    publication_metadata=pants_library('The SBT incremental compiler for nailgun')
  ),
  dependencies=[
    '3rdparty/jvm/com/github/scopt',
    '3rdparty/jvm/com/martiansoftware:nailgun-server',
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
  ],
  strict_deps=True,
  platform='java8',
)

jvm_binary(
    name = "rsc-and-zinc",
    dependencies = [
        ":rsc",
        ":compiler",
    ],
)

jar_library(
    name = "rsc",
    jars = [
        jar(
            org = "com.twitter",
            # NB: Rsc must be published with 2.12 to keep up with the recent change in upstream
            # pants which uses zinc with 2.12! This causes one test to fail in the rsc repo and must
            # be published with publish-m2 (ivy publishes don't produce a pom, or something)
            name = "rsc_2.12",
            rev = "0.0.0-733-05951a97-20190208-1804",
            url = 'file:///Users/dmcclanahan/.ivy2/local/com.twitter/rsc_2.12/0.0.0-733-05951a97-20190208-1736/jars/rsc_2.12.jar',
            mutable = True,
        ),
        jar(
          org = 'com.twitter',
          name = 'scalasig_2.12',
          rev = 'xxx',
          url = 'file:///Users/dmcclanahan/.m2/repository/com/twitter/scalasig_2.12/0.0.0-733-05951a97-20190211-1714/scalasig_2.12-0.0.0-733-05951a97-20190211-1714.jar',
          mutable = True,
        ),
        jar(
          org = 'org.scalameta',
          name = 'semanticdb-scalac_2.12.8',
          rev = '4.1.1',
        ),
    ],
)
