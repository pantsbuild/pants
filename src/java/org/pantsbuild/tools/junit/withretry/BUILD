# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
    platform = "java7",
    provides = artifact(
        name = "junit-runner-withretry",
        org = "org.pantsbuild",
        publication_metadata = pants_library("""
      Provides an org.junit.runner.Runner that supports retries of failing tests.
    """),
        repo = public,
    ),
    dependencies = [
        "3rdparty:junit",
    ],
)
