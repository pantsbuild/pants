# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, Optional

from pants.backend.python.target_types import COMMON_PYTHON_FIELDS, PythonInterpreterCompatibility
from pants.engine.addresses import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    InvalidFieldException,
    SequenceField,
    Sources,
    StringField,
    StringSequenceField,
    Target,
)

# -----------------------------------------------------------------------------------------------
# `alias` target
# -----------------------------------------------------------------------------------------------


class AliasTargetRequestedAddress(StringField):
    alias = "target"


class AliasTarget(Target):
    alias = "alias"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, AliasTargetRequestedAddress)
    deprecated_removal_version = "2.1.0.dev0"
    deprecated_removal_hint = (
        "The `alias` target was removed. If you found this feature useful, we'd be happy to add it"
        "back in a more powerful way. Please message us on Slack or open a GitHub issue "
        "(https://www.pantsbuild.org/docs/community)."
    )


# -----------------------------------------------------------------------------------------------
# `prep_command` target
# -----------------------------------------------------------------------------------------------


class PrepCommandExecutable(StringField):
    alias = "prep_executable"
    required = True


class PrepCommandArgs(StringSequenceField):
    alias = "prep_args"


class PrepCommandEnviron(BoolField):
    alias = "prep_environ"
    default = False


class PrepCommandGoals(StringSequenceField):
    alias = "goals"
    default = ("test",)


class PrepCommand(Target):
    alias = "prep_command"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PrepCommandExecutable,
        PrepCommandArgs,
        PrepCommandEnviron,
        PrepCommandGoals,
    )
    deprecated_removal_version = "2.1.0.dev0"
    deprecated_removal_hint = (
        "The `prep_command` target was removed, as it does not fit well with the v2 engine's "
        "execution model. If you needed this functionality, please message us on Slack "
        "(https://www.pantsbuild.org/docs/community) and we will help to recreate your setup."
    )


# -----------------------------------------------------------------------------------------------
# `python_app` target
# -----------------------------------------------------------------------------------------------


class PythonAppBinaryField(StringField):
    alias = "binary"


class PythonAppBasename(StringField):
    alias = "basename"


class PythonAppArchiveFormat(StringField):
    alias = "archive"


class Bundle:
    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(self, rel_path=None, mapper=None, relative_to=None, fileset=None):
        pass


class BundlesField(SequenceField):
    alias = "bundles"
    expected_element_type = Bundle
    expected_type_description = "an iterable of `bundle` objects"

    @classmethod
    def compute_value(cls, raw_value: Optional[Iterable[Bundle]], *, address: Address) -> None:
        try:
            super().compute_value(raw_value, address=address)
        except InvalidFieldException:
            pass
        return None


class PythonApp(Target):
    alias = "python_app"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        BundlesField,
        PythonAppBinaryField,
        PythonAppBasename,
        PythonAppArchiveFormat,
    )
    deprecated_removal_version = "2.1.0.dev0"
    deprecated_removal_hint = (
        "Instead of `python_app`, use the simpler `archive` target. If you still need to relocate "
        "files, use the new `relocated_files` target. See "
        "https://www.pantsbuild.org/docs/resources."
    )


# -----------------------------------------------------------------------------------------------
# `unpacked_wheels` target
# -----------------------------------------------------------------------------------------------


class UnpackedWheelsModuleName(StringField):
    alias = "module_name"
    required = True


class UnpackedWheelsRequestedLibraries(StringSequenceField):
    alias = "libraries"
    required = True


class UnpackedWheelsIncludePatterns(StringSequenceField):
    alias = "include_patterns"


class UnpackedWheelsExcludePatterns(StringSequenceField):
    alias = "exclude_patterns"


class UnpackedWheelsWithinDataSubdir(BoolField):
    alias = "within_data_subdir"
    default = False


class UnpackedWheels(Target):
    alias = "unpacked_whls"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonInterpreterCompatibility,
        UnpackedWheelsModuleName,
        UnpackedWheelsRequestedLibraries,
        UnpackedWheelsIncludePatterns,
        UnpackedWheelsExcludePatterns,
        UnpackedWheelsWithinDataSubdir,
    )
    deprecated_removal_version = "2.1.0.dev0"
    deprecated_removal_hint = (
        "The `unpacked_wheels` target type was removed. Please reach out if you'd still like this "
        "functionality (https://www.pantsbuild.org/docs/community)."
    )


# -----------------------------------------------------------------------------------------------
# `python_grpcio_library` target
# -----------------------------------------------------------------------------------------------


class PythonGrpcioLibrary(Target):
    alias = "python_grpcio_library"
    core_fields = (*COMMON_PYTHON_FIELDS, Dependencies, Sources)
    deprecated_removal_version = "2.1.0.dev0"
    deprecated_removal_hint = (
        "Instead of `python_grpcio_library`, use `protobuf_library(grpc=True)`. See "
        "https://www.pantsbuild.org/docs/protobuf."
    )
