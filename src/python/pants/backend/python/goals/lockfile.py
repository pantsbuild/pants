# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Sequence

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
from pants.engine.process import ProcessResult
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
    resolve_name: str
    lockfile_dest: str
    # Only kept for `[python-setup].experimental_lockfile`, which is not using the new
    # "named resolve" semantics yet.
    _description: str | None = None
    _regenerate_command: str | None = None

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
            resolve_name=subsystem.options_scope,
            lockfile_dest=subsystem.lockfile,
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
            description=req._description or f"Generate lockfile for {req.resolve_name}",
        ),
    )
    poetry_export_result = await Get(
        ProcessResult,
        VenvPexProcess(
            poetry_pex,
            argv=("export", "-o", req.lockfile_dest),
            input_digest=poetry_lock_result.output_digest,
            output_files=(req.lockfile_dest,),
            description=(
                f"Exporting Poetry lockfile to requirements.txt format for {req.resolve_name}"
            ),
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
            python_setup.lockfile_custom_regeneration_command
            or req._regenerate_command
            or f"./pants generate-lockfiles --resolve={req.resolve_name}"
        ),
    )
    final_lockfile_digest = await Get(
        Digest, CreateDigest([FileContent(req.lockfile_dest, lockfile_with_header)])
    )
    return PythonLockfile(final_lockfile_digest, req.lockfile_dest)


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

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--resolve",
            type=list,
            member_type=str,
            advanced=False,
            help=(
                "Only generate lockfiles for the specified resolve(s).\n\n"
                "For now, resolves are the options scope for each Python tool that supports "
                "lockfiles, such as `black`, `pytest`, and `mypy-protobuf`. For example, you can "
                "run `./pants generate-lockfiles --resolve=black --resolve=pytest` to only "
                "generate the lockfile for those two tools.\n\n"
                "If you specify an invalid resolve name, like 'fake', Pants will output all "
                "possible values.\n\n"
                "If not specified, will generate for all resolves."
            ),
        )

    @property
    def resolve_names(self) -> tuple[str, ...]:
        return tuple(self.options.resolves)


class GenerateLockfilesGoal(Goal):
    subsystem_cls = GenerateLockfilesSubsystem


@goal_rule
async def generate_lockfiles_goal(
    workspace: Workspace,
    union_membership: UnionMembership,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
) -> GenerateLockfilesGoal:
    # TODO(#12314): this factoring requires that `PythonLockfileRequest`s need to be calculated
    #  for tools even if the user does not want to generate a lockfile for that tool. That code
    #  can be quite slow when it requires computing interpreter constraints.
    all_requests = await MultiGet(
        Get(PythonLockfileRequest, PythonToolLockfileSentinel, sentinel())
        for sentinel in union_membership.get(PythonToolLockfileSentinel)
    )

    results = await MultiGet(
        Get(PythonLockfile, PythonLockfileRequest, req)
        for req in determine_resolves_to_generate(
            all_requests, generate_lockfiles_subsystem.resolve_names
        )
    )
    merged_digest = await Get(Digest, MergeDigests(res.digest for res in results))
    workspace.write_digest(merged_digest)
    for result in results:
        logger.info(f"Wrote lockfile to {result.path}")

    return GenerateLockfilesGoal(exit_code=0)


class UnrecognizedResolveNamesError(Exception):
    pass


def determine_resolves_to_generate(
    all_tool_lockfile_requests: Sequence[PythonLockfileRequest],
    requested_resolve_names: Sequence[str],
) -> list[PythonLockfileRequest]:
    if not requested_resolve_names:
        return [
            req
            for req in all_tool_lockfile_requests
            if req.lockfile_dest not in (NO_TOOL_LOCKFILE, DEFAULT_TOOL_LOCKFILE)
        ]

    resolve_names_to_requests = {
        request.resolve_name: request for request in all_tool_lockfile_requests
    }

    specified_requests = []
    unrecognized_resolve_names = []
    for resolve_name in requested_resolve_names:
        request = resolve_names_to_requests.get(resolve_name)
        if request:
            if request.lockfile_dest in (NO_TOOL_LOCKFILE, DEFAULT_TOOL_LOCKFILE):
                logger.warning(
                    f"You requested to generate a lockfile for {request.resolve_name} because "
                    "you included it in `--generate-lockfiles-resolve`, but "
                    f"`[{request.resolve_name}].lockfile` is set to `{request.lockfile_dest}` "
                    "so a lockfile will not be generated.\n\n"
                    f"If you would like to generate a lockfile for {request.resolve_name}, please "
                    f"set `[{request.resolve_name}].lockfile` to the path where it should be "
                    "generated and run again."
                )
            else:
                specified_requests.append(request)
        else:
            unrecognized_resolve_names.append(resolve_name)

    if unrecognized_resolve_names:
        # TODO(#12314): maybe implement "Did you mean?"
        if len(unrecognized_resolve_names) == 1:
            unrecognized_str = unrecognized_resolve_names[0]
            name_description = "name"
        else:
            unrecognized_str = str(sorted(unrecognized_resolve_names))
            name_description = "names"
        raise UnrecognizedResolveNamesError(
            f"Unrecognized resolve {name_description} from the option "
            f"`--generate-lockfiles-resolve`: {unrecognized_str}\n\n"
            f"All valid resolve names: {sorted(resolve_names_to_requests.keys())}"
        )

    return specified_requests


def rules():
    return collect_rules()
