# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.targets import COMMON_PYTHON_FIELDS
from pants.engine.target import Sources, Target


class PythonThriftLibrary(Target):
    """A Python library generated from Thrift IDL files."""

    alias = "python_thrift_library"
    core_fields = (*COMMON_PYTHON_FIELDS, Sources)
    v1_only = True
