# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any, Dict, Optional, Type, cast

from pants.build_graph.address import Address
from pants.build_graph.target import Target as TargetV1
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    InvalidFieldTypeException,
    PrimitiveField,
    Sources,
    StringField,
    StringSequenceField,
    Target,
)


class FilesSources(Sources):
    required = True


class Files(Target):
    """A collection of loose files which do not have their source roots stripped.

    The sources of a `files` target can be accessed via language-specific APIs, such as Python's
    `open()`. Unlike the similar `resources()` target type, Pants will not strip the source root of
    `files()`, meaning that `src/python/project/f1.txt` will not be stripped down to
    `project/f1.txt`.
    """

    alias = "files"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, FilesSources)


class ResourcesSources(Sources):
    required = True


class Resources(Target):
    """A collection of loose files.

    The sources of a `resources` target can be accessed via language-specific APIs, such as Python's
    `open()`. Resources are meant to be included in deployable units like JARs or Python wheels.
    Unlike the similar `files()` target type, Pants will strip the source root of `resources()`,
    meaning that `src/python/project/f1.txt` will be stripped down to `project/f1.txt`.
    """

    alias = "resources"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ResourcesSources)


class GenericTarget(Target):
    """A generic target with no specific target type.

    This is useful for aggregate targets: https://www.pantsbuild.org/target_aggregate.html.
    """

    alias = "target"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies)


class AliasTargetRequestedAddress(StringField):
    """The address to the target that you are creating an alias for, e.g.
    `src/python/project:lib`."""

    alias = "target"
    required = True


# TODO: figure out how to support aliases in V2. Is this a simple example of codegen, perhaps?
class AliasTarget(Target):
    """A target that gets replaced by the address specified in the `target` field.

    See https://www.pantsbuild.org/alias.html.
    """

    alias = "alias"
    core_fields = (*COMMON_TARGET_FIELDS, AliasTargetRequestedAddress)


class PrepCommandExecutable(StringField):
    """The path to the executable that should be run."""

    alias = "prep_executable"
    required = True


class PrepCommandArgs(StringSequenceField):
    """A list of command-line args to the executable."""

    alias = "prep_args"


class PrepCommandEnviron(BoolField):
    """If True, the output of the command will be treated as a \\\\0-separated list of key=value
    pairs to insert into the environment.

    Note that this will pollute the environment for all future tests, so avoid it if at all
    possible.
    """

    alias = "prep_environ"
    default = False


class PrepCommandGoals(StringSequenceField):
    """One or more pants goals to run this command in, e.g. `["test", "binary", "compile"]`."""

    alias = "goals"
    default = ("test",)


# TODO(#9388): maybe remove? Audit V1 usages.
class PrepCommand(Target):
    """A V1-only shell command to be run prior to running a goal.

    For example, you can use `prep_command()` to execute a script that sets up tunnels to database
    servers. These tunnels could then be leveraged by integration tests.

    Pants will only execute the `prep_command()` under the specified goal, when processing targets
    that depend on the `prep_command()` target.  If not otherwise specified, prep_commands
    execute in the test goal.

    See also the target type jvm_prep_command() for running tasks defined by a JVM language.
    """

    alias = "prep_command"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PrepCommandExecutable,
        PrepCommandArgs,
        PrepCommandEnviron,
        PrepCommandGoals,
    )


class RemoteSourcesTargetRequestedAddress(StringField):
    """The address of the target which specifies the JAR whose sources will be unpacked.

    Usually, this is an `unpacked_jars()` target.
    """

    alias = "sources_target"
    required = True


class RemoteSourcesTargetType(PrimitiveField):
    """The target type of the synthetic target to generate.

    Use the raw symbol rather than a string, e.g. `java_library` rather than `"java_library"`.
    """

    alias = "dest"
    required = True
    value: Type[TargetV1]

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Type[TargetV1]], *, address: Address
    ) -> Type[TargetV1]:
        # TODO: Once we switch over symbols to refer to V2 targets, we will need to convert back
        # the V2 target to the V1 target before passing this down to the V1 code.
        return cast(Type[TargetV1], super().compute_value(raw_value, address=address))


class RemoteSourcesArgs(PrimitiveField):
    """Any additional arguments necessary to construct the synthetic destination target (sources and
    dependencies are supplied automatically)."""

    alias = "args"
    value: Optional[Dict[str, Any]]
    default = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Dict[str, Any]], *, address: Address
    ) -> Optional[Dict[str, Any]]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is not None and not isinstance(value_or_default, dict):
            raise InvalidFieldTypeException(
                address, cls.alias, value_or_default, expected_type="a dictionary"
            )
        return value_or_default


# TODO: figure out what support looks like for this in V2. Is this an example of codegen?
class RemoteSources(Target):
    """A target that generates a synthetic target using deferred sources.

    This provides a mechanism for using the contents of a JAR as sources for another target.
    """

    alias = "remote_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        RemoteSourcesTargetRequestedAddress,
        RemoteSourcesTargetType,
        RemoteSourcesArgs,
    )
