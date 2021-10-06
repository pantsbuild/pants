# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

deploy_jar(
    name="example_app_deploy_jar",
    main="org.pantsbuild.example.app.ExampleApp",
    dependencies=[
        ":app",
    ],
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
    requirements = [":com.fasterxml.jackson.core_jackson-databind"],
    sources = [
        "coursier_resolve.lockfile",
    ],
)
