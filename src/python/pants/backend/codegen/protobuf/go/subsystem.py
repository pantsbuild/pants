# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import cast

from pants.option.subsystem import Subsystem


class GoProtobufSubsystem(Subsystem):
    options_scope = "go-protobuf"
    help = (
        "Go protobuf generator (https://pkg.go.dev/google.golang.org/protobuf/cmd/protoc-gen-go)."
    )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--version",
            type=str,
            default="v1.27.1",
            help=(
                "The version of the Go protobuf plugin to use. The value of this option is used as "
                "the version query passed to `go install` to build the protoc plugin. "
                "See https://go.dev/ref/mod#version-queries for more information on the format of version queries."
            ),
        )
        register(
            "--grpc-version",
            type=str,
            default="v1.2.0",
            help=(
                "The version of the Go gRPC protobuf plugin to use. The value of this option is used as "
                "the version query passed to `go install` to build the protoc plugin. "
                "See https://go.dev/ref/mod#version-queries for more information on the format of version queries."
            ),
        )

    @property
    def version(self) -> str:
        return cast(str, self.options.version)

    @property
    def grpc_version(self) -> str:
        return cast(str, self.options.grpc_version)
