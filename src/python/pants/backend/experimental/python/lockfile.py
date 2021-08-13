# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent

from pants.backend.experimental.python.lockfile_metadata import (
    calculate_invalidation_digest,
    lockfile_content_with_header,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.target_types import EntryPoint, PythonRequirementsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, PexRequirements, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.poetry_conversions import create_pyproject_toml
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionMembership, union
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Generic lockfile generation
# --------------------------------------------------------------------------------------


class PoetrySubsystem(PythonToolRequirementsBase):
    options_scope = "poetry"
    help = "Used to generate lockfiles for third-party Python dependencies."

    default_version = "poetry==1.1.7"

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.9"]

    # TODO(#12314): add lockfile support, but that has to be manually added rather than having Pants
    #  auto-generate it to workaround chicken-and-egg.


# We must monkeypatch Poetry to include `setuptools` and `wheel` in the lockfile. This was fixed
# in Poetry 1.2. See https://github.com/python-poetry/poetry/issues/1584.
# TODO(#12314): only use this custom launcher if using Poetry 1.1. (Ban 1.0 and earlier, probably).
POETRY_LAUNCHER = FileContent(
    "__pants_poetry_launcher.py",
    dedent(
        """\
        from poetry.console import main
        from poetry.puzzle.provider import Provider

        Provider.UNSAFE_PACKAGES = set()
        main()
        """
    ).encode(),
)


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
    ) -> PythonLockfileRequest:
        """Create a request for a dedicated lockfile for the tool.

        If the tool determines its interpreter constraints by using the constraints of user code,
        rather than the option `--interpreter-constraints`, you must pass the arg
        `interpreter_constraints`.
        """
        return cls(
            requirements=FrozenOrderedSet(subsystem.all_requirements),
            interpreter_constraints=(
                interpreter_constraints
                if interpreter_constraints is not None
                else subsystem.interpreter_constraints
            ),
            dest=subsystem.lockfile,
            description=f"Generate lockfile for {subsystem.options_scope}",
            regenerate_command="./pants tool-lock",
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

    # TODO(#12314): Wire up Poetry to named_caches.
    # TODO(#12314): Wire up all the pip options like indexes.
    poetry_lock_result = await Get(
        ProcessResult,
        VenvPexProcess(
            poetry_pex,
            argv=("lock",),
            input_digest=pyproject_toml_digest,
            output_files=("poetry.lock", "pyproject.toml"),
            description=req.description,
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

    lockfile_digest_contents = await Get(DigestContents, Digest, poetry_export_result.output_digest)
    lockfile_with_header = lockfile_content_with_header(
        python_setup.lockfile_custom_regeneration_command or req.regenerate_command,
        req.requirements_hex_digest,
        req.interpreter_constraints,
        lockfile_digest_contents[0].content,
    )
    final_lockfile = await Get(Digest, CreateDigest([FileContent(req.dest, lockfile_with_header)]))

    return PythonLockfile(final_lockfile, req.dest)


# --------------------------------------------------------------------------------------
# User lockfiles
# --------------------------------------------------------------------------------------


class LockSubsystem(GoalSubsystem):
    name = "lock"
    help = "Generate a lockfile."


class LockGoal(Goal):
    subsystem_cls = LockSubsystem


@goal_rule
async def lockfile_goal(
    addresses: Addresses,
    python_setup: PythonSetup,
    workspace: Workspace,
) -> LockGoal:
    if python_setup.lockfile is None:
        logger.warning(
            "You ran `./pants lock`, but `[python-setup].experimental_lockfile` is not set. Please "
            "set this option to the path where you'd like the lockfile for your code's "
            "dependencies to live."
        )
        return LockGoal(exit_code=1)

    # TODO(#12314): Looking at the transitive closure to generate a single lockfile will not work
    #  when we have multiple lockfiles supported, via per-tool lockfiles and multiple user lockfiles.
    #  Ideally, `./pants lock ::` would mean "regenerate all unique lockfiles", whereas now it
    #  means "generate a single lockfile based on this transitive closure."
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))

    # TODO(#12314): Likely include "dev dependencies" like MyPy and Pytest, which must not have
    #  conflicting versions with user requirements. This is a simpler alternative to shading, which
    #  is likely out of scope for the project. See https://github.com/pantsbuild/pants/issues/9206.
    #
    #  We may want to redesign how you set the version and requirements for subsystems in the
    #  process. Perhaps they should be directly a python_requirement_library, and you use a target
    #  address? Pytest is a particularly weird case because it's often both a tool you run _and_
    #  something you import.
    #
    #  Make sure to not break https://github.com/pantsbuild/pants/issues/10819.
    reqs = PexRequirements.create_from_requirement_fields(
        tgt[PythonRequirementsField]
        # NB: By looking at the dependencies, rather than the closure, we only generate for
        # requirements that are actually used in the project.
        #
        # TODO(#12314): It's not totally clear to me if that is desirable. Consider requirements like
        #  pydevd-pycharm. Should that be in the lockfile? I think this needs to be the case when
        #  we have multiple lockfiles, though: we shouldn't look at the universe in that case,
        #  only the relevant subset of requirements.
        #
        #  Note that the current generate_lockfile.sh script in our docs also mixes in
        #  `requirements.txt`, but not inlined python_requirement_library targets if they're not
        #  in use. We don't have a way to emulate those semantics because at this point, all we
        #  have is `python_requirement_library` targets without knowing the source.
        for tgt in transitive_targets.dependencies
        if tgt.has_field(PythonRequirementsField)
    )

    if not reqs:
        logger.warning(
            "No third-party requirements found for the transitive closure, so a lockfile will not "
            "be generated."
        )
        return LockGoal(exit_code=0)

    result = await Get(
        PythonLockfile,
        PythonLockfileRequest(
            reqs.req_strings,
            # TODO(#12314): Figure out which interpreter constraints to use. Likely get it from the
            #  transitive closure. When we're doing a single global lockfile, it's fine to do that,
            #  but we need to figure out how this will work with multiple resolves.
            InterpreterConstraints(python_setup.interpreter_constraints),
            dest=python_setup.lockfile,
            description=(
                f"Generate lockfile for {pluralize(len(reqs.req_strings), 'requirement')}: "
                f"{', '.join(reqs.req_strings)}"
            ),
            # TODO(12382): Make this command actually accurate once we figure out the semantics
            #  for user lockfiles. This is currently misleading.
            regenerate_command="./pants lock ::",
        ),
    )
    workspace.write_digest(result.digest)
    logger.info(f"Wrote lockfile to {result.path}")

    return LockGoal(exit_code=0)


# --------------------------------------------------------------------------------------
# Tool lockfiles
# --------------------------------------------------------------------------------------


@union
class PythonToolLockfileSentinel:
    pass


# TODO(#12314): Unify this goal with `lock` once we figure out how to unify the semantics,
#  particularly w/ CLI specs. This is a separate goal only to facilitate progress.
class ToolLockSubsystem(GoalSubsystem):
    name = "tool-lock"
    help = "Generate a lockfile for a Python tool."
    required_union_implementations = (PythonToolLockfileSentinel,)


class ToolLockGoal(Goal):
    subsystem_cls = ToolLockSubsystem


@goal_rule
async def generate_all_tool_lockfiles(
    workspace: Workspace,
    union_membership: UnionMembership,
) -> ToolLockGoal:
    # TODO(#12314): Add logic to inspect the Specs and generate for only relevant lockfiles. For
    #  now, we generate for all tools.
    requests = await MultiGet(
        Get(PythonLockfileRequest, PythonToolLockfileSentinel, sentinel())
        for sentinel in union_membership.get(PythonToolLockfileSentinel)
    )
    if not requests:
        return ToolLockGoal(exit_code=0)

    results = await MultiGet(
        Get(PythonLockfile, PythonLockfileRequest, req)
        for req in requests
        if req.dest not in {"<none>", "<default>"}
    )
    merged_digest = await Get(Digest, MergeDigests(res.digest for res in results))
    workspace.write_digest(merged_digest)
    for result in results:
        logger.info(f"Wrote lockfile to {result.path}")

    return ToolLockGoal(exit_code=0)


def rules():
    return collect_rules()
