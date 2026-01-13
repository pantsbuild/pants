load("@grpc//bazel:cc_grpc_library.bzl", "cc_grpc_library")
load("@protobuf//bazel:cc_proto_library.bzl", "cc_proto_library")
load("@protobuf//bazel:java_proto_library.bzl", "java_proto_library")
load("@rules_go//go:def.bzl", "go_library")
load("@rules_go//proto:def.bzl", "go_proto_library")
load("@rules_proto//proto:defs.bzl", "proto_library")

package(default_visibility = ["//visibility:public"])

licenses(["notice"])

proto_library(
    name = "remote_logstream_proto",
    srcs = ["remote_logstream.proto"],
)

# Java
java_proto_library(
    name = "remote_logstream_java_proto",
    deps = ["//build/bazel/remote/logstream/v1:remote_logstream_proto"],
)

# C++
cc_proto_library(
    name = "remote_logstream_cc_proto",
    deps = ["//build/bazel/remote/logstream/v1:remote_logstream_proto"],
)

cc_grpc_library(
    name = "remote_logstream_cc_grpc",
    srcs = ["//build/bazel/remote/logstream/v1:remote_logstream_proto"],
    grpc_only = True,
    deps = [":remote_logstream_cc_proto"],
)

# Go
go_proto_library(
    name = "remote_logstream_go_proto",
    compilers = [
        "@rules_go//proto:go_proto",
        "@rules_go//proto:go_grpc_v2",
    ],
    importpath = "github.com/bazelbuild/remote-apis/build/bazel/remote/logstream/v1",
    proto = ":remote_logstream_proto",
)

go_library(
    name = "go_default_library",
    embed = [":remote_logstream_go_proto"],
    importpath = "github.com/bazelbuild/remote-apis/build/bazel/remote/logstream/v1",
)
