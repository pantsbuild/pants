# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonProvidesField
from pants.backend.python.util_rules.partition import _find_all_unique_interpreter_constraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.goals.package import PackageFieldSet
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class PythonDistributionFieldSet(PackageFieldSet):
    required_fields = (PythonProvidesField,)

    provides: PythonProvidesField


class Setuptools(PythonToolRequirementsBase):
    options_scope = "setuptools"
    help = "Python setuptools, used to package `python_distribution` targets."

    default_version = "setuptools>=63.1.0,<64.0"
    default_extra_requirements = ["wheel>=0.35.1,<0.38"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "setuptools.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/setuptools.lock"
    default_lockfile_url = git_url(default_lockfile_path)


class SetuptoolsLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = Setuptools.options_scope


@rule(
    desc=softwrap(
        """
        Determine all Python interpreter versions used by setuptools in your project
        (for lockfile generation)
        """
    ),
    level=LogLevel.DEBUG,
)
async def setup_setuptools_lockfile(
    _: SetuptoolsLockfileSentinel, setuptools: Setuptools, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    if not setuptools.uses_custom_lockfile:
        return GeneratePythonLockfile.from_tool(
            setuptools, use_pex=python_setup.generate_lockfiles_with_pex
        )

    interpreter_constraints = await _find_all_unique_interpreter_constraints(
        python_setup, PythonDistributionFieldSet
    )
    return GeneratePythonLockfile.from_tool(
        setuptools, interpreter_constraints, use_pex=python_setup.generate_lockfiles_with_pex
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, SetuptoolsLockfileSentinel),
    )
