# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

from pants.backend.experimental.python.lockfile_metadata import (
    calculate_invalidation_digest,
    lockfile_content_with_header,
)
from pants.backend.python.subsystems.python_tool_base import (
    PythonToolBase,
    PythonToolRequirementsBase,
)
from pants.backend.python.target_types import ConsoleScript, PythonRequirementsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, PexRequirements, VenvPex, VenvPexProcess
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


class PipToolsSubsystem(PythonToolBase):
    options_scope = "pip-tools"
    help = "Used to generate lockfiles for third-party Python dependencies."

    default_version = "pip-tools==6.2.0"
    default_main = ConsoleScript("pip-compile")

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        # TODO(#12314): How should users indicate where to save the lockfile to when we have
        #  per-tool lockfiles and multiple user lockfiles?
        register(
            "--lockfile-dest",
            type=str,
            default="3rdparty/python/lockfile.txt",
            help="The file path to be created.\n\nThis will overwrite any previous files.",
        )

    @property
    def lockfile_dest(self) -> str:
        return cast(str, self.options.lockfile_dest)


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
    def hex_digest(self) -> str:
        """Produces a hex digest of this lockfile's inputs, which should uniquely specify the
        resolution of this lockfile request.

        Inputs are definted as requirements and interpreter constraints.
        """
        return calculate_invalidation_digest(self.requirements, self.interpreter_constraints)


@rule(desc="Generate lockfile", level=LogLevel.DEBUG)
async def generate_lockfile(
    req: PythonLockfileRequest, pip_tools_subsystem: PipToolsSubsystem, python_setup: PythonSetup
) -> PythonLockfile:
    reqs_filename = "reqs.txt"
    input_requirements = await Get(
        Digest, CreateDigest([FileContent(reqs_filename, "\n".join(req.requirements).encode())])
    )

    pip_compile_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="pip_compile.pex",
            internal_only=True,
            requirements=pip_tools_subsystem.pex_requirements,
            interpreter_constraints=req.interpreter_constraints,
            main=pip_tools_subsystem.main,
            description=(
                "Building pip_compile.pex with interpreter constraints: "
                f"{req.interpreter_constraints}"
            ),
        ),
    )

    generated_lockfile = await Get(
        ProcessResult,
        # TODO(#12314): Figure out named_caches for pip-tools. The best would be to share
        #  the cache between Pex and Pip. Next best is a dedicated named_cache.
        VenvPexProcess(
            pip_compile_pex,
            description=req.description,
            # TODO(#12314): Wire up all the pip options like indexes.
            argv=[
                reqs_filename,
                "--generate-hashes",
                f"--output-file={req.dest}",
                # NB: This allows pinning setuptools et al, which we must do. This will become
                # the default in a future version of pip-tools.
                "--allow-unsafe",
            ],
            input_digest=input_requirements,
            output_files=(req.dest,),
        ),
    )

    _lockfile_contents_iter = await Get(DigestContents, Digest, generated_lockfile.output_digest)
    lockfile_contents = _lockfile_contents_iter[0]

    content_with_header = lockfile_content_with_header(
        python_setup.lockfile_custom_regeneration_command or req.regenerate_command,
        req.hex_digest,
        lockfile_contents.content,
    )
    complete_lockfile = await Get(
        Digest, CreateDigest([FileContent(req.dest, content_with_header)])
    )

    return PythonLockfile(complete_lockfile, req.dest)


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
    pip_tools_subsystem: PipToolsSubsystem,
    python_setup: PythonSetup,
    workspace: Workspace,
) -> LockGoal:
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
            dest=pip_tools_subsystem.lockfile_dest,
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
