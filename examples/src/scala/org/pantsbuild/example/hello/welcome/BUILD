# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Seq-friendly wrapper for Java "greet" library: greet everything in a seq.

scala_library(
    provides = scala_artifact(
        name = "welcome",
        org = "org.pantsbuild.example.hello",
        repo = public,
    ),
    dependencies = [
        "examples/src/java/org/pantsbuild/example/hello/greet",
        "examples/src/resources/org/pantsbuild/example/hello",
    ],
)
