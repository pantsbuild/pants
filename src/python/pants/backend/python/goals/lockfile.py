# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.python.subsystems.poetry import (
    POETRY_LAUNCHER,
    PoetrySubsystem,
    create_pyproject_toml,
)
from pants.backend.python.subsystems.python_tool_base import (
    DEFAULT_TOOL_LOCKFILE,
    NO_TOOL_LOCKFILE,
    PythonToolRequirementsBase,
)
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    LockfileMetadata,
    calculate_invalidation_digest,
)
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.unions import UnionMembership, union
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Generic lockfile generation
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonLockfile:
    digest: Digest
    path: str


@dataclass(frozen=True)
class PythonLockfileRequest:
    requirements: FrozenOrderedSet[str]
    interpreter_constraints: InterpreterConstraints
    dest: str
    description: str
    regenerate_command: str

    @classmethod
    def from_tool(
        cls,
        subsystem: PythonToolRequirementsBase,
        interpreter_constraints: InterpreterConstraints | None = None,
        *,
        extra_requirements: Iterable[str] = (),
    ) -> PythonLockfileRequest:
        """Create a request for a dedicated lockfile for the tool.

        If the tool determines its interpreter constraints by using the constraints of user code,
        rather than the option `--interpreter-constraints`, you must pass the arg
        `interpreter_constraints`.
        """
        return cls(
            requirements=FrozenOrderedSet((*subsystem.all_requirements, *extra_requirements)),
            interpreter_constraints=(
                interpreter_constraints
                if interpreter_constraints is not None
                else subsystem.interpreter_constraints
            ),
            dest=subsystem.lockfile,
            description=f"Generate lockfile for {subsystem.options_scope}",
            regenerate_command="./pants generate-lockfiles",
        )

    @property
    def requirements_hex_digest(self) -> str:
        """Produces a hex digest of the requirements input for this lockfile."""
        return calculate_invalidation_digest(self.requirements)


@rule(desc="Generate lockfile", level=LogLevel.DEBUG)
async def generate_lockfile(
    req: PythonLockfileRequest, poetry_subsystem: PoetrySubsystem, python_setup: PythonSetup
) -> PythonLockfile:
    pyproject_toml = create_pyproject_toml(req.requirements, req.interpreter_constraints).encode()
    pyproject_toml_digest, launcher_digest = await MultiGet(
        Get(Digest, CreateDigest([FileContent("pyproject.toml", pyproject_toml)])),
        Get(Digest, CreateDigest([POETRY_LAUNCHER])),
    )

    poetry_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="poetry.pex",
            internal_only=True,
            requirements=poetry_subsystem.pex_requirements(),
            interpreter_constraints=poetry_subsystem.interpreter_constraints,
            main=EntryPoint(PurePath(POETRY_LAUNCHER.path).stem),
            sources=launcher_digest,
        ),
    )

    # WONTFIX(#12314): Wire up Poetry to named_caches.
    # WONTFIX(#12314): Wire up all the pip options like indexes.
    poetry_lock_result = await Get(
        ProcessResult,
        VenvPexProcess(
            poetry_pex,
            argv=("lock",),
            input_digest=pyproject_toml_digest,
            output_files=("poetry.lock", "pyproject.toml"),
            description=req.description,
            # Instead of caching lockfile generation with LMDB, we instead use the invalidation
            # scheme from `lockfile_metadata.py` to check for stale/invalid lockfiles. This is
            # necessary so that our invalidation is resilient to deleting LMDB or running on a
            # new machine.
            #
            # We disable caching with LMDB so that when you generate a lockfile, you always get
            # the most up-to-date snapshot of the world. This is generally desirable and also
            # necessary to avoid an awkward edge case where different developers generate different
            # lockfiles even when generating at the same time. See
            # https://github.com/pantsbuild/pants/issues/12591.
            cache_scope=ProcessCacheScope.PER_SESSION,
        ),
    )
    poetry_export_result = await Get(
        ProcessResult,
        VenvPexProcess(
            poetry_pex,
            argv=("export", "-o", req.dest),
            input_digest=poetry_lock_result.output_digest,
            output_files=(req.dest,),
            description=(f"Exporting Poetry lockfile to requirements.txt format for {req.dest}"),
            level=LogLevel.DEBUG,
        ),
    )

    initial_lockfile_digest_contents = await Get(
        DigestContents, Digest, poetry_export_result.output_digest
    )
    metadata = LockfileMetadata(req.requirements_hex_digest, req.interpreter_constraints)
    lockfile_with_header = metadata.add_header_to_lockfile(
        initial_lockfile_digest_contents[0].content,
        regenerate_command=(
            python_setup.lockfile_custom_regeneration_command or req.regenerate_command
        ),
    )
    final_lockfile_digest = await Get(
        Digest, CreateDigest([FileContent(req.dest, lockfile_with_header)])
    )
    return PythonLockfile(final_lockfile_digest, req.dest)


# --------------------------------------------------------------------------------------
# Lock goal
# --------------------------------------------------------------------------------------


@union
class PythonToolLockfileSentinel:
    pass


class GenerateLockfilesSubsystem(GoalSubsystem):
    name = "generate-lockfiles"
    help = "Generate lockfiles for Python third-party dependencies."
    required_union_implementations = (PythonToolLockfileSentinel,)


class GenerateLockfilesGoal(Goal):
    subsystem_cls = GenerateLockfilesSubsystem


@goal_rule
async def generate_lockfiles_goal(
    workspace: Workspace, union_membership: UnionMembership
) -> GenerateLockfilesGoal:
    requests = await MultiGet(
        Get(PythonLockfileRequest, PythonToolLockfileSentinel, sentinel())
        for sentinel in union_membership.get(PythonToolLockfileSentinel)
    )
    if not requests:
        return GenerateLockfilesGoal(exit_code=0)

    results = await MultiGet(
        Get(PythonLockfile, PythonLockfileRequest, req)
        for req in requests
        if req.dest not in {NO_TOOL_LOCKFILE, DEFAULT_TOOL_LOCKFILE}
    )
    merged_digest = await Get(Digest, MergeDigests(res.digest for res in results))
    workspace.write_digest(merged_digest)
    for result in results:
        logger.info(f"Wrote lockfile to {result.path}")

    return GenerateLockfilesGoal(exit_code=0)


def rules():
    return collect_rules()
