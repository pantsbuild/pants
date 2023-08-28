# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.jvm.resolve.jvm_tool import JvmToolBase


class JavaProtobufGrpcSubsystem(JvmToolBase):
    options_scope = "protobuf-java-grpc"
    help = "gRPC support for Java Protobuf (https://github.com/grpc/grpc-java)"

    default_version = "1.48.0"
    default_artifacts = (
        "io.grpc:protoc-gen-grpc-java:exe:linux-aarch_64:{version}",
        "io.grpc:protoc-gen-grpc-java:exe:linux-x86_64:{version}",
        "io.grpc:protoc-gen-grpc-java:exe:osx-aarch_64:{version}",
        "io.grpc:protoc-gen-grpc-java:exe:osx-x86_64:{version}",
    )
    default_lockfile_resource = (
        "pants.backend.codegen.protobuf.java",
        "grpc-java.default.lockfile.txt",
    )
