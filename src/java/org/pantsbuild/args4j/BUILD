# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
    platform = "java7",
    provides = artifact(
        name = "args4j",
        org = "org.pantsbuild",
        publication_metadata = pants_library("""
      Utilities to make args4j more like com.twitter.common#args
    """),
        repo = public,
    ),
    dependencies = [
        "3rdparty:args4j",
        "3rdparty:guava",
        "3rdparty:jsr305",
    ],
)
