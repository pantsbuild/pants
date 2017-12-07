# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
    name = "nailgun-server",
    jars = [jar(
        name = "nailgun-server",
        org = "com.martiansoftware",
        rev = "0.9.1",
    )],
)

jar_library(
    name = "jmake",
    jars = [jar(
        name = "jmake",
        org = "org.pantsbuild",
        rev = "1.3.8-10",
    )],
)

jar_library(
    name = "zinc",
    jars = [
        jar(
            name = "zinc",
            org = "com.typesafe.zinc",
            rev = "0.3.7",
        ),
    ],
)

java_library(
    name = "foo",
    sources = globs("Main.java"),
    dependencies = [
        ":baz",
        ":zinc",
    ],
    excludes = [
        exclude("com.martiansoftware", "nailgun-server"),  # :bar depends on this
        exclude("org.pantsbuild"),  # :bar depends on this
        exclude("com.typesafe.sbt", "incremental-compiler"),
        exclude("com.typesafe.sbt", "sbt-interface"),
    ],
)

java_library(
    name = "bar",
    sources = globs("Main.java"),
    dependencies = [
        ":jmake",
        ":nailgun-server",
    ],
)

java_library(
    name = "baz",
    sources = globs("Main.java"),
)
