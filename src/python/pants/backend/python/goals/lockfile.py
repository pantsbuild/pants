# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar, Iterable, Sequence, cast

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
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@union
class PythonToolLockfileSentinel:
    options_scope: ClassVar[str]


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
        register(
            "--custom-command",
            advanced=True,
            type=str,
            default=None,
            help=(
                "If set, lockfile headers will say to run this command to regenerate the lockfile, "
                "rather than running `./pants generate-lockfiles --resolve=<name>` like normal."
            ),
        )

    @property
    def resolve_names(self) -> tuple[str, ...]:
        return tuple(self.options.resolve)

    @property
    def custom_command(self) -> str | None:
        return cast("str | None", self.options.custom_command)


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
        if not subsystem.uses_lockfile:
            return cls(
                FrozenOrderedSet(),
                InterpreterConstraints(),
                resolve_name=subsystem.options_scope,
                lockfile_dest=subsystem.lockfile,
            )
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
    req: PythonLockfileRequest,
    poetry_subsystem: PoetrySubsystem,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
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
            generate_lockfiles_subsystem.custom_command
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


class GenerateLockfilesGoal(Goal):
    subsystem_cls = GenerateLockfilesSubsystem


@goal_rule
async def generate_lockfiles_goal(
    workspace: Workspace,
    union_membership: UnionMembership,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
) -> GenerateLockfilesGoal:
    specified_tool_requests = await MultiGet(
        Get(PythonLockfileRequest, PythonToolLockfileSentinel, sentinel())
        for sentinel in determine_tool_sentinels_to_generate(
            union_membership[PythonToolLockfileSentinel],
            generate_lockfiles_subsystem.resolve_names,
        )
    )
    results = await MultiGet(
        Get(PythonLockfile, PythonLockfileRequest, req)
        for req in filter_tool_lockfile_requests(
            specified_tool_requests,
            resolve_specified=bool(generate_lockfiles_subsystem.resolve_names),
        )
    )

    merged_digest = await Get(Digest, MergeDigests(res.digest for res in results))
    workspace.write_digest(merged_digest)
    for result in results:
        logger.info(f"Wrote lockfile to {result.path}")

    return GenerateLockfilesGoal(exit_code=0)


class UnrecognizedResolveNamesError(Exception):
    pass


def determine_tool_sentinels_to_generate(
    all_tool_sentinels: Iterable[type[PythonToolLockfileSentinel]],
    requested_resolve_names: Sequence[str],
) -> list[type[PythonToolLockfileSentinel]]:
    if not requested_resolve_names:
        return list(all_tool_sentinels)

    resolve_names_to_sentinels = {
        sentinel.options_scope: sentinel for sentinel in all_tool_sentinels
    }
    specified_sentinels = []
    unrecognized_resolve_names = []
    for resolve_name in requested_resolve_names:
        sentinel = resolve_names_to_sentinels.get(resolve_name)
        if sentinel:
            specified_sentinels.append(sentinel)
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
            f"All valid resolve names: {sorted(resolve_names_to_sentinels.keys())}"
        )

    return specified_sentinels


def filter_tool_lockfile_requests(
    specified_requests: Sequence[PythonLockfileRequest], *, resolve_specified: bool
) -> list[PythonLockfileRequest]:
    result = []
    for req in specified_requests:
        if req.lockfile_dest not in (NO_TOOL_LOCKFILE, DEFAULT_TOOL_LOCKFILE):
            result.append(req)
            continue
        if resolve_specified:
            resolve = req.resolve_name
            raise ValueError(
                f"You requested to generate a lockfile for {resolve} because "
                "you included it in `--generate-lockfiles-resolve`, but "
                f"`[{resolve}].lockfile` is set to `{req.lockfile_dest}` "
                "so a lockfile will not be generated.\n\n"
                f"If you would like to generate a lockfile for {resolve}, please "
                f"set `[{resolve}].lockfile` to the path where it should be "
                "generated and run again."
            )

    return result


def rules():
    return collect_rules()
