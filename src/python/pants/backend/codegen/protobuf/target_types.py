# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, Target


class ProtobufSources(Sources):
    default = ("*.proto",)


class ProtobufLibrary(Target):
    """Protobuf files used to generate various languages.

    See https://developers.google.com/protocol-buffers/.
    """

    alias = "protobuf_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ProtobufSources)
