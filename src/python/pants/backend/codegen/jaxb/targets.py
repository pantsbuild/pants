# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.rules.targets import COMMON_JVM_FIELDS
from pants.engine.target import Sources, StringField, Target


class JaxbJavaPackage(StringField):
    """Java package (com.company.package) in which to generate the output Java files.

    If unspecified, Pants guesses it from the file path leading to the schema (xsd) file. This guess
    is accurate only if the .xsd file is in a path like `.../com/company/package/schema.xsd`. Pants
    looks for packages that start with 'com', 'org', or 'net'.
    """

    alias = "package"


class JaxbLanguage(StringField):
    """The language to use, which currently can only be `java`."""

    alias = "language"
    valid_choices = ("java",)
    default = "java"
    value: str


class JaxbLibrary(Target):
    """A Java library generated from JAXB xsd files."""

    alias = "jaxb_library"
    core_fields = (*COMMON_JVM_FIELDS, Sources, JaxbJavaPackage, JaxbLanguage)
    v1_only = True
