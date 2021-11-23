# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

deploy_jar(
    name="example_app_deploy_jar",
    main="org.pantsbuild.example.app.ExampleApp",
    dependencies=[":app"],
)

scala_sources(
    compatible_resolves=["exampleapp"],
)

jvm_artifact(
  name = "com.google.truth_truth",
  group = "com.google.truth",
  artifact = "truth",
  version = "0.45",
  # scope = "test",
)
