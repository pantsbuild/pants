load("@protobuf//bazel:cc_proto_library.bzl", "cc_proto_library")
load("@protobuf//bazel:java_proto_library.bzl", "java_proto_library")
load("@rules_go//go:def.bzl", "go_library")
load("@rules_go//proto:def.bzl", "go_proto_library")
load("@rules_proto//proto:defs.bzl", "proto_library")

package(default_visibility = ["//visibility:public"])

licenses(["notice"])

proto_library(
    name = "semver_proto",
    srcs = ["semver.proto"],
)

# Java
java_proto_library(
    name = "semver_java_proto",
    deps = ["//build/bazel/semver:semver_proto"],
)

# C++
cc_proto_library(
    name = "semver_cc_proto",
    deps = ["//build/bazel/semver:semver_proto"],
)

# Go
go_proto_library(
    name = "semver_go_proto",
    importpath = "github.com/bazelbuild/remote-apis/build/bazel/semver",
    proto = ":semver_proto",
)

go_library(
    name = "go_default_library",
    embed = [":semver_go_proto"],
    importpath = "github.com/bazelbuild/remote-apis/build/bazel/semver",
)
