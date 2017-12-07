# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_thrift_library(
    name = "good-thrift",
    sources = ["good.thrift"],
    compiler = "scrooge",
    compiler_args = ["--finagle"],
    language = "scala",
)

java_thrift_library(
    name = "namespace-map-thrift",
    sources = ["good.thrift"],
    compiler = "scrooge",
    compiler_args = ["--finagle"],
    language = "scala",
    namespace_map = {
        "old": "new",
    },
)

java_thrift_library(
    name = "default-java-namespace-thrift",
    sources = ["good.thrift"],
    compiler = "scrooge",
    compiler_args = ["--finagle"],
    default_java_namespace = "the_namespace",
    language = "scala",
)

java_thrift_library(
    name = "include-paths-thrift",
    sources = ["good.thrift"],
    compiler = "scrooge",
    compiler_args = ["--finagle"],
    include_paths = [
        "some_dir",
    ],
    language = "scala",
)

java_thrift_library(
    name = "both-compiler-args-and-rpc-style",
    sources = ["good.thrift"],
    compiler = "scrooge",
    compiler_args = ["--finagle"],
    language = "scala",
    rpc_style = "finagle",
)
