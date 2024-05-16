# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import EntryPoint
from pants.engine.rules import collect_rules


class SetuptoolsSCM(PythonToolBase):
    options_scope = "setuptools-scm"
    help_short = (
        "A tool for generating versions from VCS metadata (https://github.com/pypa/setuptools_scm)."
    )

    default_main = EntryPoint("setuptools_scm")
    default_requirements = ["setuptools-scm>=6.4.2,<8"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.subsystems", "setuptools_scm.lock")


def rules():
    return collect_rules()
