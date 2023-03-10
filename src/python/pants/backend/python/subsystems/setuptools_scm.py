# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import EntryPoint
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url


class SetuptoolsSCM(PythonToolBase):
    options_scope = "setuptools-scm"
    help = (
        "A tool for generating versions from VCS metadata (https://github.com/pypa/setuptools_scm)."
    )

    default_version = "setuptools-scm==7.1.0"
    default_main = EntryPoint("setuptools_scm")
    default_requirements = ["setuptools-scm>=6.4.2,<8"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "setuptools_scm.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/setuptools_scm.lock"
    default_lockfile_url = git_url(default_lockfile_path)


class SetuptoolsSCMLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = SetuptoolsSCM.options_scope


@rule
def setup_setuptools_scm_lockfile(
    _: SetuptoolsSCMLockfileSentinel, setuptools_scm: SetuptoolsSCM
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(setuptools_scm)


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, SetuptoolsSCMLockfileSentinel),
    )
