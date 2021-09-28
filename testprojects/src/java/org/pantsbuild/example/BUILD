# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_sources(
    dependencies=[
      ":lockfile",
    ],
)

jvm_artifact(
    name = "com.fasterxml.jackson.core_jackson-annotations",
    group = "com.fasterxml.jackson.core",
    artifact = "jackson-annotations",
    version = "2.12.5",
)

jvm_artifact(
    name = "com.fasterxml.jackson.core_jackson-core",
    group = "com.fasterxml.jackson.core",
    artifact = "jackson-core",
    version = "2.12.5",
)

jvm_artifact(
    name = "com.fasterxml.jackson.core_jackson-databind",
    group = "com.fasterxml.jackson.core",
    artifact = "jackson-databind",
    version = "2.12.5",
)

coursier_lockfile(
    name = "lockfile",
    requirements = [
        ":com.fasterxml.jackson.core_jackson-annotations",
        ":com.fasterxml.jackson.core_jackson-core",
        ":com.fasterxml.jackson.core_jackson-databind",
    ],
    sources = [
        "coursier_resolve.lockfile",
    ],
)
