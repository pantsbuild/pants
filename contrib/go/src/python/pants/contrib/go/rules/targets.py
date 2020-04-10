# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    Sources,
    StringField,
    StringSequenceField,
    Target,
)

# -----------------------------------------------------------------------------------------------
# Common fields
# -----------------------------------------------------------------------------------------------


class GoSources(Sources):
    # NB: We glob on `*` due to the way resources and .c companion files are handled.
    default = ("*", "!BUILD", "!BUILD.*")


# -----------------------------------------------------------------------------------------------
# `go_binary` target
# -----------------------------------------------------------------------------------------------


class GoBuildFlags(StringField):
    """Build flags to pass to the Go compiler."""

    alias = "build_flags"


class GoBinary(Target):
    """A Go main package."""

    alias = "go_binary"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, GoSources, GoBuildFlags)
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `go_library` target
# -----------------------------------------------------------------------------------------------


class GoLibrary(Target):
    """A Go package."""

    alias = "go_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, GoSources)
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `go_protobuf_library` target
# -----------------------------------------------------------------------------------------------


class GoProtobufSources(Sources):
    default = ("*.proto",)


class ProtocPlugins(StringSequenceField):
    """Protoc plugins to use when generating code from this target."""

    alias = "protoc_plugins"


class GoProtobufLibrary(Target):
    """A Go library generated from Protobuf IDL files."""

    alias = "go_protobuf_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, GoProtobufSources, ProtocPlugins)
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `go_thrift_library` target
# -----------------------------------------------------------------------------------------------


class GoThriftLibrary(Target):
    """A Go library generated from Thrift IDL files."""

    alias = "go_thrift_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, Sources)
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `go_remote_library` and `go_remote_libraries` targets
# -----------------------------------------------------------------------------------------------


class GoPackage(StringField):
    """The package import path within the remote library.

    By default, just the root package will be available.
    """

    alias = "pkg"
    default = "."


class GoRevision(StringField):
    """Identifies which version of the remote library to download.

    This could be a commit SHA (git), node id (hg), etc. If left unspecified the version will
    default to the latest available. It's highly recommended to not accept the default and to
    instead  pin the rev explicitly for reproducible builds.
    """

    alias = "rev"


class GoRemoteLibrary(Target):
    """A remote Go package."""

    alias = "go_remote_library"
    core_fields = (*COMMON_TARGET_FIELDS, GoPackage, GoRevision)
    v1_only = True


class GoPackages(StringSequenceField):
    """The package import paths within the remote library.

    By default, just the root package will be available.
    """

    alias = "pkg"
    default = (".",)


class GoRemoteLibraries(Target):
    """Multiple remote Go packages."""

    alias = "go_remote_libraries"
    core_fields = (*COMMON_TARGET_FIELDS, GoPackages, GoRevision)
    v1_only = True
