# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

from pants.backend.python.goals.lockfile import PythonLockfile, PythonLockfileRequest
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonRequirementsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequirements
from pants.engine.addresses import Addresses
from pants.engine.fs import Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


# TODO(#12314): Unify with the `generate-lockfiles` goal. Stop looking at specs and instead have
#  an option like `--lock-resolves` with a list of named resolves (including tools).
class GenerateUserLockfileSubsystem(GoalSubsystem):
    name = "generate-user-lockfile"
    help = "Generate a lockfile for Python user requirements (experimental)."


class GenerateUserLockfileGoal(Goal):
    subsystem_cls = GenerateUserLockfileSubsystem


@goal_rule
async def generate_user_lockfile_goal(
    addresses: Addresses,
    python_setup: PythonSetup,
    workspace: Workspace,
) -> GenerateUserLockfileGoal:
    if python_setup.lockfile is None:
        logger.warning(
            "You ran `./pants generate-user-lockfile`, but `[python].experimental_lockfile` "
            "is not set. Please set this option to the path where you'd like the lockfile for "
            "your code's dependencies to live."
        )
        return GenerateUserLockfileGoal(exit_code=1)

    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))
    reqs = PexRequirements.create_from_requirement_fields(
        tgt[PythonRequirementsField]
        # NB: By looking at the dependencies, rather than the closure, we only generate for
        # requirements that are actually used in the project.
        for tgt in transitive_targets.dependencies
        if tgt.has_field(PythonRequirementsField)
    )

    if not reqs:
        logger.warning(
            "No third-party requirements found for the transitive closure, so a lockfile will not "
            "be generated."
        )
        return GenerateUserLockfileGoal(exit_code=0)

    result = await Get(
        PythonLockfile,
        PythonLockfileRequest(
            reqs.req_strings,
            # TODO(#12314): Use interpreter constraints from the transitive closure.
            InterpreterConstraints(python_setup.interpreter_constraints),
            resolve_name="not yet implemented",
            lockfile_dest=python_setup.lockfile,
            _description=(
                f"Generate lockfile for {pluralize(len(reqs.req_strings), 'requirement')}: "
                f"{', '.join(reqs.req_strings)}"
            ),
            # TODO(12382): Make this command actually accurate once we figure out the semantics
            #  for user lockfiles. This is currently misleading.
            _regenerate_command="./pants generate-user-lockfile ::",
        ),
    )
    workspace.write_digest(result.digest)
    logger.info(f"Wrote lockfile to {result.path}")

    return GenerateUserLockfileGoal(exit_code=0)


def rules():
    return collect_rules()
