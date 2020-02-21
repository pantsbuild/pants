# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class Setuptools(PythonToolBase):
    # NB: setuptools doesn't have an entrypoint, unlike most python tools.
    # We call it via a generated setup.py script.
    options_scope = "setuptools"
    default_version = "setuptools==42.0.2"
    default_extra_requirements = ["wheel==0.31.1"]
