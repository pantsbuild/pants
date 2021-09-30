# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

deploy_jar(
    name="example_lib_deploy_jar",
    main="org.pantsbuild.example.ExampleLib",
    root_address=":example",
)

java_sources(
    dependencies=[
      ":lockfile",
    ],
)

coursier_lockfile(
    name = "lockfile",
    requirements = [],
    sources = [
        "coursier_resolve.lockfile",
    ],
)
