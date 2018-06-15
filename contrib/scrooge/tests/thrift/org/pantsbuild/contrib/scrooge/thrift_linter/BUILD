# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_thrift_library(
    name = "bad-thrift-default",
    sources = ["bad-default.thrift"],
    tags = ["nolint"],
    # thrift_linter_strict not defined
)

java_thrift_library(
    name = "bad-thrift-strict",
    sources = ["bad-strict.thrift"],
    tags = ["nolint"],
    thrift_linter_strict = True,
)

java_thrift_library(
    name = "bad-thrift-strict2",
    sources = ["bad-strict2.thrift"],
    tags = ["nolint"],
    thrift_linter_strict = True,
)

java_thrift_library(
    name = "bad-thrift-non-strict",
    sources = ["bad-non-strict.thrift"],
    tags = ["nolint"],
    thrift_linter_strict = False,
)

java_thrift_library(
    name = "good-thrift",
    sources = ["good.thrift"],
    tags = ["nolint"],
    thrift_linter_strict = True,
)
