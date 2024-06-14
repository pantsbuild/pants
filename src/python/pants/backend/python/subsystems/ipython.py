# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.core.goals.resolves import ExportableTool
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption
from pants.util.strutil import softwrap


class IPython(PythonToolBase):
    options_scope = "ipython"
    help_short = "The IPython enhanced REPL (https://ipython.org/)."

    default_main = ConsoleScript("ipython")
    default_requirements = ["ipython>=7.34,<9"]
    default_interpreter_constraints = ["CPython>=3.8,<4"]

    default_lockfile_resource = ("pants.backend.python.subsystems", "ipython.lock")

    ignore_cwd = BoolOption(
        advanced=True,
        default=True,
        help=softwrap(
            """
            Whether to tell IPython not to put the CWD on the import path.

            Normally you want this to be True, so that imports come from the hermetic
            environment Pants creates.

            However IPython<7.13.0 doesn't support this option, so if you're using an earlier
            version (e.g., because you have Python 2.7 code) then you will need to set this to False,
            and you may have issues with imports from your CWD shading the hermetic environment.
            """
        ),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(ExportableTool, IPython),
    )
