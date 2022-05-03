# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonProvidesField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.goals.package import PackageFieldSet
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    AllTargetsRequest,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonDistributionFieldSet(PackageFieldSet):
    required_fields = (PythonProvidesField,)

    provides: PythonProvidesField


class Setuptools(PythonToolRequirementsBase):
    options_scope = "setuptools"
    help = "Python setuptools, used to package `python_distribution` targets."

    default_version = "setuptools>=50.3.0,<58.0"
    default_extra_requirements = ["wheel>=0.35.1,<0.38"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "setuptools.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/setuptools.lock"
    default_lockfile_url = git_url(default_lockfile_path)


class SetuptoolsLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = Setuptools.options_scope


@rule(
    desc=(
        "Determine all Python interpreter versions used by setuptools in your project "
        "(for lockfile generation)"
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

    all_tgts = await Get(AllTargets, AllTargetsRequest())
    transitive_targets_per_python_dist = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest([tgt.address]))
        for tgt in all_tgts
        if PythonDistributionFieldSet.is_applicable(tgt)
    )
    unique_constraints = {
        InterpreterConstraints.create_from_targets(transitive_targets.closure, python_setup)
        or InterpreterConstraints(python_setup.interpreter_constraints)
        for transitive_targets in transitive_targets_per_python_dist
    }
    constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))
    return GeneratePythonLockfile.from_tool(
        setuptools,
        constraints or InterpreterConstraints(python_setup.interpreter_constraints),
        use_pex=python_setup.generate_lockfiles_with_pex,
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, SetuptoolsLockfileSentinel),
    )
