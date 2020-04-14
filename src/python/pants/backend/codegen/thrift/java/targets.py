# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.rules.targets import COMMON_JVM_FIELDS
from pants.engine.target import (
    BoolField,
    DictStringToStringField,
    Sources,
    StringField,
    StringSequenceField,
    Target,
)


class JavaThriftCompiler(StringField):
    """The compiler used to compile the thrift files.

    The default is defined in the global options under `--thrift-default-compiler`.
    """

    alias = "compiler"
    valid_choices = ("thrift", "scrooge")


class JavaThriftLanguage(StringField):
    """The language used to generate the output files.

    The default is defined in the global options under `--thrift-default-language`.
    """

    alias = "language"


class JavaThriftNamespaceMap(DictStringToStringField):
    """An optional dictionary of namespaces to remap: {old: new}."""

    alias = "namespace_map"


class JavaThriftLinterStrict(BoolField):
    """If True, fail if thrift linter produces any warnings."""

    alias = "thrift_linter_strict"
    default = False


class JavaThriftDefaultNamespace(StringField):
    """The namespace used for Java generated code when a Java namespace is not explicitly specified
    in the IDL.

    The default is defined in the global options under `--thrift-default-default-java-namespace`.
    """

    alias = "default_java_namespace"


class JavaThriftIncludePaths(StringSequenceField):
    alias = "include_paths"


class JavaThriftCompilerArgs(StringSequenceField):
    """Extra arguments to the compiler."""

    alias = "compiler_args"


class JavaThriftLibrary(Target):
    """A Java library generated from Thrift IDL files."""

    alias = "java_thrift_library"
    core_fields = (
        *COMMON_JVM_FIELDS,
        Sources,
        JavaThriftCompiler,
        JavaThriftLanguage,
        JavaThriftNamespaceMap,
        JavaThriftLinterStrict,
        JavaThriftDefaultNamespace,
        JavaThriftIncludePaths,
        JavaThriftCompilerArgs,
    )
    v1_only = True
