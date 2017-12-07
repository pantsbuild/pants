# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library(
    platform = "java8",
    provides = scala_artifact(
        name = "zinc-cache",
        org = "org.pantsbuild",
        publication_metadata = pants_library("The SBT incremental compiler for nailgun"),
        repo = public,
    ),
    strict_deps = True,
    dependencies = [
        "3rdparty:guava",
        "3rdparty:jsr305",
    ],
    exports = [
        "3rdparty:guava",
    ],
)
