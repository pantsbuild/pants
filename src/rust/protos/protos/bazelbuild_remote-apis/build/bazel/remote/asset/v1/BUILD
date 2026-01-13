load("@grpc//bazel:cc_grpc_library.bzl", "cc_grpc_library")
load("@protobuf//bazel:cc_proto_library.bzl", "cc_proto_library")
load("@protobuf//bazel:java_proto_library.bzl", "java_proto_library")
load("@rules_go//go:def.bzl", "go_library")
load("@rules_go//proto:def.bzl", "go_proto_library")
load("@rules_proto//proto:defs.bzl", "proto_library")

package(default_visibility = ["//visibility:public"])

licenses(["notice"])

proto_library(
    name = "remote_asset_proto",
    srcs = ["remote_asset.proto"],
    deps = [
        "//build/bazel/remote/execution/v2:remote_execution_proto",
        "@googleapis//google/api:annotations_proto",
        "@googleapis//google/rpc:status_proto",
        "@protobuf//:duration_proto",
        "@protobuf//:timestamp_proto",
    ],
)

# Java
java_proto_library(
    name = "remote_asset_java_proto",
    deps = [":remote_asset_proto"],
)

# C++
cc_proto_library(
    name = "remote_asset_cc_proto",
    deps = [":remote_asset_proto"],
)

cc_grpc_library(
    name = "remote_asset_cc_grpc",
    srcs = [":remote_asset_proto"],
    grpc_only = True,
    deps = [":remote_asset_cc_proto"],
)

# Go
go_proto_library(
    name = "remote_asset_go_proto",
    compilers = [
        "@rules_go//proto:go_proto",
        "@rules_go//proto:go_grpc_v2",
    ],
    importpath = "github.com/bazelbuild/remote-apis/build/bazel/remote/asset/v1",
    proto = ":remote_asset_proto",
    deps = [
        "//build/bazel/remote/execution/v2:remote_execution_go_proto",
        "@org_golang_google_genproto_googleapis_api//annotations",
        "@org_golang_google_genproto_googleapis_rpc//status",
    ],
)

go_library(
    name = "go_default_library",
    embed = [":remote_asset_go_proto"],
    importpath = "github.com/bazelbuild/remote-apis/build/bazel/remote/asset/v1",
)
