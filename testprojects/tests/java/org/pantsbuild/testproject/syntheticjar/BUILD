# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
    name = "util",
    sources = ["Util.java"],
    dependencies = [],
)

jvm_binary(
    name = "run",
    main = "org.pantsbuild.testproject.syntheticjar.run.SyntheticJarRun",
    source = "SyntheticJarRun.java",
    dependencies = [
        ":util",
    ],
)

junit_tests(
    name = "test",
    sources = ["SyntheticJarTest.java"],
    dependencies = [
        ":util",
        "3rdparty:junit",
    ],
)
