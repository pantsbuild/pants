# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

fat_jar(
    name="example_lib_fat_jar",
    main=":example",
)

java_sources(
    dependencies=[
      ":lockfile",
    ],
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
        ":com.fasterxml.jackson.core_jackson-databind",  # Has jackson-core and jackson annotations as dependencies
    ],
    sources = [
        "coursier_resolve.lockfile",
    ],
)
