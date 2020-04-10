# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.rules.targets import COMMON_JVM_FIELDS
from pants.engine.target import BoolField, Sources, StringField, StringSequenceField, Target


class JavaWireServiceWriter(StringField):
    """The name of the class to pass as the --service_writer option to the Wire compiler.

    For Wire 1.0 only.
    """

    alias = "service_writer"


class JavaWireServiceWriterOptions(StringSequenceField):
    """A list of options to pass to the service writer.

    For Wire 1.x only.
    """

    alias = "service_writer_options"


class JavaWireRoots(StringSequenceField):
    """Passed through to the --roots option of the Wire compiler."""

    alias = "roots"


class JavaWireRegistryClass(StringField):
    """fully qualified class name of RegistryClass to create.

    If in doubt, specify com.squareup.wire.SimpleServiceWriter.
    """

    alias = "registry_class"


class JavaWireEnumOptions(StringSequenceField):
    """List of enums to pass to as the --enum-enum_options option."""

    alias = "enum_options"


class JavaWireNoOptionsToggle(BoolField):
    """Boolean that determines if --no_options flag is passed."""

    alias = "no_options"
    default = False


class JavaWireOrderedSources(BoolField):
    """Boolean that declares whether the sources argument represents literal ordered sources to be
    passed directly to the compiler.

    If false, no ordering is guaranteed for the sources passed to an individual compiler invoke.
    """

    alias = "ordered_sources"
    default = False


class JavaWireLibrary(Target):
    """A Java library generated from Wire IDL files.

    Supports Wire 1.x only.

    For an example Wire 2.x interface that generates service stubs see:
    https://github.com/ericzundel/mvn2pants/tree/master/src/python/squarepants/plugins/sake_wire_codegen

    But note this requires you to write a custom wire code generator with a command line interface.
    """

    alias = "java_wire_library"
    core_fields = (
        *COMMON_JVM_FIELDS,
        Sources,
        JavaWireServiceWriter,
        JavaWireServiceWriterOptions,
        JavaWireRoots,
        JavaWireRegistryClass,
        JavaWireEnumOptions,
        JavaWireNoOptionsToggle,
        JavaWireOrderedSources,
    )
    v1_only = True
