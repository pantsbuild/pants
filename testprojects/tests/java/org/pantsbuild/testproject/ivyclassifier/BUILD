# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(
    sources = ["IvyClassifierTest.java"],
    dependencies = [
        ":jars_with_classifier",
        "3rdparty:junit",
        "testprojects/tests/resources/org/pantsbuild/testproject/ivyclassifier",
    ],
)

jar_library(
    name = "jars_with_classifier",
    jars = [
        jar(
            org = "org.apache.avro",
            name = "avro",
            rev = "1.7.7",
        ),
        jar(
            org = "org.apache.avro",
            name = "avro",
            classifier = "tests",
            rev = "1.7.7",
        ),
    ],
)
