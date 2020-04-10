# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.rules.targets import COMMON_JVM_FIELDS
from pants.engine.target import Sources, StringField, Target


class JavaAntlrSources(Sources):
    required = True


class AntlrCompiler(StringField):
    """The name of the compiler used to compile the ANTLR files."""

    alias = "compiler"
    valid_choices = ("antlr3", "antlr4")
    value: str
    default = "antlr3"


class AntlrPackage(StringField):
    """(antlr4 only) A string which specifies the package to be used on the dependent sources.

    If unspecified, the package will be based on the path to the sources. Note that if the sources
    are spread among different files, this must be set as the package cannot be inferred.
    """

    alias = "package"


class JavaAntlrLibrary(Target):
    """A Java library generated from Antlr grammar files."""

    alias = "java_antlr_library"
    core_fields = (*COMMON_JVM_FIELDS, JavaAntlrSources, AntlrCompiler, AntlrPackage)
    v1_only = True
