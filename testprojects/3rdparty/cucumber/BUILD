# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
    name = "cuke-core",
    jars = [
        jar(
            name = "cucumber-core",
            org = "info.cukes",
            rev = "1.2.4",
        ),
    ],
)

jar_library(
    name = "cuke-guice",
    jars = [
        jar(
            name = "cucumber-guice",
            org = "info.cukes",
            rev = "1.2.4",
        ),
    ],
    dependencies = [
        # The cucumber-guice jar has a 'provided' scope dep on guice itself so we're forced to adjoin
        # a direct (runtime) dep here.
        scoped(
            ":com.google.inject.guice",
            scope = "runtime",
        ),
    ],
)

jar_library(
    name = "cuke-java",
    jars = [
        jar(
            name = "cucumber-java",
            org = "info.cukes",
            rev = "1.2.4",
        ),
    ],
)

jar_library(
    name = "cuke-junit",
    jars = [
        jar(
            name = "cucumber-junit",
            org = "info.cukes",
            rev = "1.2.4",
        ),
    ],
)

jar_library(
    name = "com.google.inject.guice",
    jars = [
        jar(
            name = "guice",
            org = "com.google.inject",
            rev = "4.0",
        ),
    ],
)
