# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.targets import COMMON_PYTHON_FIELDS
from pants.engine.target import Sources, StringField, Target


class AntlrModule(StringField):
    """Everything beneath module is relative to this module name.

    Do not define if the root namespace.
    """

    alias = "module"


class AntlrVersion(StringField):
    """A Python library generated from Antlr grammar files."""

    alias = "version"
    value: str
    default = "3.1.3"


class PythonAntlrLibrary(Target):
    """A Python library generated from Antlr grammar files."""

    alias = "python_antlr_library"
    core_fields = (*COMMON_PYTHON_FIELDS, Sources, AntlrModule, AntlrVersion)
    v1_only = True
