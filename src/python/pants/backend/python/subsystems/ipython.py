# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript


class IPython(PythonToolBase):
    options_scope = "ipython"
    help = "The IPython enhanced REPL (https://ipython.org/)."

    default_version = "ipython==7.16.1"  # The last version to support Python 3.6.
    default_main = ConsoleScript("ipython")

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--ignore-cwd",
            type=bool,
            advanced=True,
            default=True,
            help="Whether to tell IPython not to put the CWD on the import path.\n\n"
            "Normally you want this to be True, so that imports come from the hermetic "
            "environment Pants creates.\n\nHowever IPython<7.13.0 doesn't support this option, "
            "so if you're using an earlier version (e.g., because you have Python 2.7 code) "
            "then you will need to set this to False, and you may have issues with imports "
            "from your CWD shading the hermetic environment.",
        )
