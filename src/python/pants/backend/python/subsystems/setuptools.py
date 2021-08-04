# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools

from pants.backend.experimental.python.lockfile import (
    PythonLockfileRequest,
    PythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.target_types import PythonProvidesField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest, UnexpandedTargets
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.docutil import git_url
from pants.util.logging import LogLevel


class Setuptools(PythonToolRequirementsBase):
    options_scope = "setuptools"
    help = "Python setuptools, used to package `python_distribution` targets."

    default_version = "setuptools>=50.3.0,<57.0"
    default_extra_requirements = ["wheel>=0.35.1,<0.37"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "setuptools_lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/setuptools_lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)


class SetuptoolsLockfileSentinel(PythonToolLockfileSentinel):
    pass


@rule(
    desc="Determine all Python interpreter versions used by setuptools in your project",
    level=LogLevel.DEBUG,
)
async def setup_setuptools_lockfile(
    _: SetuptoolsLockfileSentinel, setuptools: Setuptools, python_setup: PythonSetup
) -> PythonLockfileRequest:
    if python_setup.disable_mixed_interpreter_constraints:
        constraints = InterpreterConstraints(python_setup.interpreter_constraints)
    else:
        all_build_targets = await Get(UnexpandedTargets, AddressSpecs([DescendantAddresses("")]))
        transitive_targets_per_python_dist = await MultiGet(
            Get(TransitiveTargets, TransitiveTargetsRequest([tgt.address]))
            for tgt in all_build_targets
            if tgt.has_field(PythonProvidesField)
        )
        unique_constraints = {
            InterpreterConstraints.create_from_targets(transitive_targets.closure, python_setup)
            or InterpreterConstraints(python_setup.interpreter_constraints)
            for transitive_targets in transitive_targets_per_python_dist
        }
        constraints = InterpreterConstraints(itertools.chain.from_iterable(unique_constraints))

    return PythonLockfileRequest.from_tool(
        setuptools, constraints or InterpreterConstraints(python_setup.interpreter_constraints)
    )


def rules():
    return (*collect_rules(), UnionRule(PythonToolLockfileSentinel, SetuptoolsLockfileSentinel))
