# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
    name = "finagle-thrift",
    jars = [
        scala_jar(
            name = "finagle-thrift",
            org = "com.twitter",
            rev = "6.28.0",
            excludes = [
                exclude(
                    name = "libthrift",
                    org = "org.apache.thrift",
                ),
            ],
        ),
    ],
    dependencies = [
        "3rdparty:thrift-0.6.1",
    ],
)

jar_library(
    name = "scrooge-core",
    jars = [
        scala_jar(
            name = "scrooge-core",
            org = "com.twitter",
            rev = "3.20.0",
            excludes = [
                exclude(
                    name = "libthrift",
                    org = "org.apache.thrift",
                ),
            ],
        ),
    ],
    dependencies = [
        "3rdparty:thrift-0.6.1",
    ],
)
