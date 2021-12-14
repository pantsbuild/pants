# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import cast

from pants.option.subsystem import Subsystem


class GoProtobufSubsystem(Subsystem):
    options_scope = "go-protobuf"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--version",
            type=str,
            default="v1.27.1",
            help=("The version of the protobuf Go plugin to use."),
        )
        register(
            "--grpc-version",
            type=str,
            default="v1.2.0",
            help=("The version of the protobuf Go gRPC plugin to use."),
        )

    @property
    def version(self) -> str:
        return cast(str, self.options.version)

    @property
    def grpc_version(self) -> str:
        return cast(str, self.options.grpc_version)
