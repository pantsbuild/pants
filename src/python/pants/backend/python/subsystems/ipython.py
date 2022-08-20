# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript, InterpreterConstraintsField
from pants.backend.python.util_rules.partition import _find_all_unique_interpreter_constraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption
from pants.util.docutil import git_url
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


class IPython(PythonToolBase):
    options_scope = "ipython"
    help = "The IPython enhanced REPL (https://ipython.org/)."

    default_version = "ipython>=7.34,<8"  # ipython 8 does not support Python 3.7.
    default_main = ConsoleScript("ipython")

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "ipython.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/ipython.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    ignore_cwd = BoolOption(
        "--ignore-cwd",
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


class IPythonLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = IPython.options_scope


class _IpythonFieldSetForLockfiles(FieldSet):
    required_fields = (InterpreterConstraintsField,)


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by iPython in your project
        (for lockfile generation)
        """
    ),
    level=LogLevel.DEBUG,
)
async def setup_ipython_lockfile(
    _: IPythonLockfileSentinel, ipython: IPython, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    if not ipython.uses_custom_lockfile:
        return GeneratePythonLockfile.from_tool(
            ipython, use_pex=python_setup.generate_lockfiles_with_pex
        )

    interpreter_constraints = await _find_all_unique_interpreter_constraints(
        python_setup, _IpythonFieldSetForLockfiles
    )
    return GeneratePythonLockfile.from_tool(
        ipython, interpreter_constraints, use_pex=python_setup.generate_lockfiles_with_pex
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, IPythonLockfileSentinel),
    )
