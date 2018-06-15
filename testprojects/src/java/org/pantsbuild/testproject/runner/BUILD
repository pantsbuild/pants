# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
    name = "main-class",
    sources = ["MainClass.java"],
    dependencies = [
        ":dependent-class",
    ],
)

java_library(
    name = "dependent-class",
    sources = ["DependentClass.java"],
    dependencies = [],
)

jvm_binary(
    name = "pants-runner-testproject",
    dependencies = [
        ":main-class",
    ],
)
