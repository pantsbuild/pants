# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, BoolField, Dependencies, Sources, Target


# NB: We subclass Dependencies so that specific backends can add dependency injection rules to
# Protobuf targets.
class ProtobufDependencies(Dependencies):
    pass


class ProtobufSources(Sources):
    default = ("*.proto",)
    expected_file_extensions = (".proto",)


class ProtobufGrcpToggle(BoolField):
    """Whether to generate gRPC code or not."""

    alias = "grpc"
    default = False


class ProtobufLibrary(Target):
    """Protobuf files used to generate various languages.

    See https://www.pantsbuild.org/docs/protobuf.
    """

    alias = "protobuf_library"
    core_fields = (*COMMON_TARGET_FIELDS, ProtobufDependencies, ProtobufSources, ProtobufGrcpToggle)
