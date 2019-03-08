package(default_visibility = ["//visibility:public"])

licenses(["notice"])

proto_library(
    name = "semver_proto",
    srcs = ["semver.proto"],
)

java_proto_library(
    name = "semver_java_proto",
    deps = [":semver_proto"],
)
