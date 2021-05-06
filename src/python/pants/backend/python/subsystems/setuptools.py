# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase


class Setuptools(PythonToolRequirementsBase):
    options_scope = "setuptools"
    help = "The Python setuptools library (https://github.com/pypa/setuptools)."

    default_version = "setuptools>=50.3.0,<57.0"
    default_extra_requirements = ["wheel>=0.35.1,<0.37"]
