# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

remote_sources(
    dest = java_protobuf_library,
    sources_target = ":external-source",
)

unpacked_jars(
    name = "external-source",
    include_patterns = [
        "com/squareup/testing/**/*.proto",
    ],
    libraries = [":external-source-jars"],
)

jar_library(
    name = "external-source-jars",
    jars = [
        jar(
            name = "protolib-external-test",
            org = "com.squareup.testing.protolib",
            rev = "0.0.2",
        ),
    ],
)
