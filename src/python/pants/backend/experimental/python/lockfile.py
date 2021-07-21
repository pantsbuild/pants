# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import cast

from pants.backend.python.subsystems.python_tool_base import (
    PythonToolBase,
    PythonToolRequirementsBase,
)
from pants.backend.python.target_types import ConsoleScript, PythonRequirementsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, PexRequirements, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_environment import MaybePythonExecutable
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
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------------------
# Generic lockfile generation
# --------------------------------------------------------------------------------------


class MissingInterpretersBehavior(Enum):
    warn = "warn"
    error = "error"


class PipToolsSubsystem(PythonToolBase):
    options_scope = "pip-tools"
    help = "Used to generate lockfiles for third-party Python dependencies."

    default_version = "pip-tools==6.2.0"
    default_main = ConsoleScript("pip-compile")

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        # TODO(#12314): Find a proper home for this. This could be it, but maybe [python-setup] or
        #  a new [python-lockfiles] are more appropriate? We keep it here for now to feature gate
        #  it.
        register(
            "--lockfile-missing-interpreters-behavior",
            type=MissingInterpretersBehavior,
            # TODO(#12314): Once we implement merging logic, update pantsbuild/pants to error. Even
            #  if we keep the default at warning, we should error for Pants to ensure that our
            #  default lockfiles we generate are always valid.
            default=MissingInterpretersBehavior.warn,
            help=(
                "What to do if interpreters used by your code or tools you run are not "
                "discoverable when generating lockfiles.\n\n"
                "Because some Python dependencies are only needed when using a particular Python "
                "version, Pants needs to generate a lockfile with each Python interpreter possibly "
                "used by your interpreter constraints. Pants will then merge all the lockfiles "
                "into a single, universal lockfile.\n\n"
                "For example, if you set `[python-setup].interpreter_constraints` to "
                "`['>=3.6,<3.8']`, Pants will try to generate lockfiles with Python 3.6 and 3.7, "
                "then merge into a single lockfile.\n\n"
                "If certain interpreters in the constraint range are missing, the lockfile may be "
                "invalid."
            ),
        )

    @property
    def missing_interpreters_behavior(self) -> MissingInterpretersBehavior:
        return cast(
            MissingInterpretersBehavior, self.options.lockfile_missing_interpreters_behavior
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

    @classmethod
    def from_tool(cls, subsystem: PythonToolRequirementsBase) -> PythonLockfileRequest:
        return cls(
            requirements=FrozenOrderedSet(subsystem.all_requirements),
            interpreter_constraints=subsystem.interpreter_constraints,
            dest=subsystem.lockfile,
            description=subsystem.options_scope,
        )


@dataclass(frozen=True)
class _MergeLockfilesRequest:
    major_minor_version_to_lockfile: FrozenDict[str, FileContent]


@rule(desc="Generate lockfile", level=LogLevel.DEBUG)
async def generate_lockfile(
    req: PythonLockfileRequest, pip_tools_subsystem: PipToolsSubsystem, python_setup: PythonSetup
) -> PythonLockfile:
    input_requirements = await Get(
        Digest, CreateDigest([FileContent("reqs.txt", "\n".join(req.requirements).encode())])
    )

    major_minor_versions_to_ics = req.interpreter_constraints.partition_by_major_minor_versions(
        python_setup.interpreter_universe
    )
    maybe_python_per_ics = await MultiGet(
        Get(MaybePythonExecutable, InterpreterConstraints, ic)
        for ic in major_minor_versions_to_ics.values()
    )

    valid_versions_to_ics = {}
    missing_versions_to_ics = {}
    for major_minor, ic, maybe_python in zip(
        major_minor_versions_to_ics.keys(),
        major_minor_versions_to_ics.values(),
        maybe_python_per_ics,
    ):
        if maybe_python.python:
            valid_versions_to_ics[major_minor] = ic
        else:
            missing_versions_to_ics[major_minor] = ic

    if missing_versions_to_ics:
        if not valid_versions_to_ics:
            raise ()
        _handle_missing_interpreters(
            missing_versions_to_ics,
            pip_tools_subsystem.missing_interpreters_behavior,
            lockfile_description=req.description,
        )

    pip_compile_pexes = await MultiGet(
        Get(
            VenvPex,
            PexRequest(
                output_filename="pip_compile.pex",
                internal_only=True,
                requirements=pip_tools_subsystem.pex_requirements,
                interpreter_constraints=ic,
                main=pip_tools_subsystem.main,
                description=f"Build pip_compile.pex with Python {major_minor}",
            ),
        )
        for major_minor, ic in valid_versions_to_ics.items()
    )

    results = await MultiGet(
        Get(
            ProcessResult,
            # TODO(#12314): Figure out named_caches for pip-tools. The best would be to share
            #  the cache between Pex and Pip. Next best is a dedicated named_cache.
            VenvPexProcess(
                pip_compile,
                description=f"Generate lockfile for {req.description} with Python {major_minor}",
                # TODO(#12314): Wire up all the pip options like indexes.
                argv=[
                    "reqs.txt",
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
        for pip_compile, major_minor in zip(pip_compile_pexes, valid_versions_to_ics.keys())
    )

    lockfiles = await MultiGet(Get(DigestContents, Digest, res.output_digest) for res in results)
    versions_to_lockfiles = {
        major_minor: digest_contents[0]
        for major_minor, digest_contents in zip(valid_versions_to_ics.keys(), lockfiles)
    }
    return await Get(PythonLockfile, _MergeLockfilesRequest(FrozenDict(versions_to_lockfiles)))


@rule(desc="Merge lockfiles generated for each relevant interpreter version", level=LogLevel.DEBUG)
async def merge_lockfiles(request: _MergeLockfilesRequest) -> PythonLockfile:
    # TODO(#12314): Properly merge these files into a single one. A simple first step could be to
    #  detect conflicts and warn so that the user can manually fix.
    first_lockfile = next(iter(request.major_minor_version_to_lockfile.values()))
    digest = await Get(Digest, CreateDigest([first_lockfile]))
    return PythonLockfile(digest, first_lockfile.path)


class MissingPythonInterpreters(Exception):
    pass


def _handle_missing_interpreters(
    missing_versions_to_ics: dict[str, InterpreterConstraints],
    behavior: MissingInterpretersBehavior,
    lockfile_description: str,
) -> None:
    formatted_missing = "\n".join(
        f"  * Python {major_minor} (Constraint: {ic})"
        for major_minor, ic in missing_versions_to_ics.items()
    )
    warning = (
        "Could not find Python interpreters for the following Python versions when generating a "
        f"lockfile for {lockfile_description}:\n\n"
        f"{formatted_missing}\n\n"
        "Because some Python dependencies are only needed when using a particular Python version, "
        "Pants needs to generate a lockfile with each Python interpreter possibly used by your "
        "interpreter constraints. Pants will then merge all the lockfiles into a single, "
        "universal lockfile.\n\n"
        "To fix this, please either install the missing Python interpreters and ensure they're "
        "discoverable via `[python-setup].interpreter_search_path`, or tighten your interpreter "
        "constraints. (Tip: Pyenv can be useful to install multiple interpreter versions.)\n"
    )
    if behavior == MissingInterpretersBehavior.warn:
        logger.warning(warning)
    elif behavior == MissingInterpretersBehavior.error:
        warning += (
            "\nAlternatively, you can update `[pip-tools].lockfile_missing_interpreter_behavior` "
            "to `warn`, although this risks generating invalid lockfiles.\n"
        )
        raise MissingPythonInterpreters(warning)
    else:
        raise AssertionError(f"Unhandled variant for {behavior}")


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
            description=pluralize(len(reqs.req_strings), "requirements"),
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
    candidate_requests = await MultiGet(
        Get(PythonLockfileRequest, PythonToolLockfileSentinel, sentinel())
        for sentinel in union_membership.get(PythonToolLockfileSentinel)
    )
    if not candidate_requests:
        return ToolLockGoal(exit_code=0)

    requests = [req for req in candidate_requests if req.dest not in {"<none>", "<default>"}]

    results = await MultiGet(Get(PythonLockfile, PythonLockfileRequest, req) for req in requests)
    merged_digest = await Get(Digest, MergeDigests(res.digest for res in results))
    workspace.write_digest(merged_digest)
    for req, result in zip(requests, results):
        logger.info(f"Wrote lockfile for {req.description} to {result.path}")

    return ToolLockGoal(exit_code=0)


def rules():
    return collect_rules()
