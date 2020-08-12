# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class IPython(PythonToolBase):
    """The IPython enhanced REPL (https://ipython.org/)."""

    options_scope = "ipython"
    default_version = "ipython==7.17.0"
    default_extra_requirements: List[str] = []
    default_entry_point = "IPython:start_ipython"
    default_interpreter_constraints = ["CPython>=3.4"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--ignore-cwd",
            type=str,
            advanced=True,
            default=True,
            help="Whether to tell IPython not to put the CWD on the import path. "
            "Normally you want this to be True, so that imports come from the hermetic "
            "environment Pants creates.  However IPython<7.13.0 doesn't support this option, "
            "so if you're using an earlier version (e.g., because you have Python 2.7 code) "
            "then you will need to set this to False, and you may have issues with imports "
            "from your CWD shading the hermetic environment.",
        )
