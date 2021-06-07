# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, BoolField, Dependencies, Sources, Target
from pants.util.docutil import bracketed_docs_url


# NB: We subclass Dependencies so that specific backends can add dependency injection rules to
# Protobuf targets.
class ProtobufDependencies(Dependencies):
    pass


class ProtobufSources(Sources):
    default = ("*.proto",)
    expected_file_extensions = (".proto",)


class ProtobufGrpcToggle(BoolField):
    alias = "grpc"
    default = False
    help = "Whether to generate gRPC code or not."


class ProtobufLibrary(Target):
    alias = "protobuf_library"
    core_fields = (*COMMON_TARGET_FIELDS, ProtobufDependencies, ProtobufSources, ProtobufGrpcToggle)
    help = f"Protobuf files used to generate various languages.\n\nSee {bracketed_docs_url('protobuf')}."
