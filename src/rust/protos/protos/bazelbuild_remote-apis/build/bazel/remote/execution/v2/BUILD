load("@grpc//bazel:cc_grpc_library.bzl", "cc_grpc_library")
load("@protobuf//bazel:cc_proto_library.bzl", "cc_proto_library")
load("@protobuf//bazel:java_proto_library.bzl", "java_proto_library")
load("@rules_go//go:def.bzl", "go_library")
load("@rules_go//proto:def.bzl", "go_proto_library")
load("@rules_proto//proto:defs.bzl", "proto_library")

package(default_visibility = ["//visibility:public"])

licenses(["notice"])

proto_library(
    name = "remote_execution_proto",
    srcs = ["remote_execution.proto"],
    deps = [
        "//build/bazel/semver:semver_proto",
        "@googleapis//google/api:annotations_proto",
        "@googleapis//google/longrunning:operations_proto",
        "@googleapis//google/rpc:status_proto",
        "@protobuf//:any_proto",
        "@protobuf//:duration_proto",
        "@protobuf//:timestamp_proto",
        "@protobuf//:wrappers_proto",
    ],
)

# Java
java_proto_library(
    name = "remote_execution_java_proto",
    deps = ["//build/bazel/remote/execution/v2:remote_execution_proto"],
)

# C++
cc_proto_library(
    name = "remote_execution_cc_proto",
    deps = ["//build/bazel/remote/execution/v2:remote_execution_proto"],
)

cc_grpc_library(
    name = "remote_execution_cc_grpc",
    srcs = ["//build/bazel/remote/execution/v2:remote_execution_proto"],
    grpc_only = True,
    deps = [":remote_execution_cc_proto"],
)

# Go
go_proto_library(
    name = "remote_execution_go_proto",
    compilers = [
        "@rules_go//proto:go_proto",
        "@rules_go//proto:go_grpc_v2",
    ],
    importpath = "github.com/bazelbuild/remote-apis/build/bazel/remote/execution/v2",
    proto = ":remote_execution_proto",
    deps = [
        "//build/bazel/semver:semver_go_proto",
        "@com_google_cloud_go_longrunning//autogen/longrunningpb",
        "@org_golang_google_genproto_googleapis_api//annotations",
        "@org_golang_google_genproto_googleapis_rpc//status",
    ],
)

go_library(
    name = "go_default_library",
    embed = [":remote_execution_go_proto"],
    importpath = "github.com/bazelbuild/remote-apis/build/bazel/remote/execution/v2",
)
