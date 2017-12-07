# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
    platform = "java8",
    provides = scala_artifact(
        name = "zinc-compiler",
        org = "org.pantsbuild",
        publication_metadata = pants_library("The SBT incremental compiler for nailgun"),
        repo = public,
    ),
    strict_deps = True,
    dependencies = [
        "3rdparty:guava",
        "3rdparty:jsr305",
        "3rdparty/jvm/org/scala-lang/modules:scala-java8-compat",
        "3rdparty/jvm/org/scala-sbt:io",
        "3rdparty/jvm/org/scala-sbt:util-logging",
        "3rdparty/jvm/org/scala-sbt:zinc",
        "src/scala/org/pantsbuild/zinc/analysis",
        "src/scala/org/pantsbuild/zinc/cache",
        "src/scala/org/pantsbuild/zinc/options",
        "src/scala/org/pantsbuild/zinc/util",
    ],
)
