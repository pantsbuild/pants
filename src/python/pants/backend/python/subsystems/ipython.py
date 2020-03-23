# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class IPython(PythonToolBase):
    options_scope = "ipython"
    default_version = "ipython==5.8.0"
    default_extra_requirements: List[str] = []
    default_entry_point = "IPython:start_ipython"
    default_interpreter_constraints = ["CPython>=2.7,<3", "CPython>=3.4"]
