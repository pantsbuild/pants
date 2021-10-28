# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar, Iterable, Sequence, cast

from pants.backend.python.pip_requirement import PipRequirement
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
from pants.backend.python.subsystems.repos import PythonRepos
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    EntryPoint,
    InterpreterConstraintsField,
    PythonRequirementsField,
    PythonResolveField,
    UnrecognizedResolveNamesError,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    LockfileMetadata,
    calculate_invalidation_digest,
)
from pants.backend.python.util_rules.pex import PexRequest, PexRequirements, VenvPex, VenvPexProcess
from pants.engine.collection import Collection
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
from pants.engine.target import AllTargets, TransitiveTargets, TransitiveTargetsRequest
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
                "Resolves are the logical names for the different lockfiles used in your project. "
                "For your own code's dependencies, these come from the option "
                "`[python].experimental_resolves_to_lockfiles`. For tool lockfiles, resolve "
                "names are the options scope for that tool such as `black`, `pytest`, and "
                "`mypy-protobuf`.\n\n"
                "For example, you can run `./pants generate-lockfiles --resolve=black "
                "--resolve=pytest --resolve=data-science` to only generate lockfiles for those "
                "two tools and your resolve named `data-science`.\n\n"
                "If you specify an invalid resolve name, like 'fake', Pants will output all "
                "possible values.\n\n"
                "If not specified, Pants will generate lockfiles for all resolves."
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
    resolve_name: str
    path: str


@dataclass(frozen=True)
class PythonLockfileRequest:
    requirements: FrozenOrderedSet[str]
    interpreter_constraints: InterpreterConstraints
    resolve_name: str
    lockfile_dest: str
    # Only kept for `[python].experimental_lockfile`, which is not using the new
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
    # TODO(#12314) Improve error message on `Requirement.parse`
    metadata = LockfileMetadata.new(
        req.interpreter_constraints,
        {PipRequirement.parse(i) for i in req.requirements},
    )
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
    return PythonLockfile(final_lockfile_digest, req.resolve_name, req.lockfile_dest)


# --------------------------------------------------------------------------------------
# User lockfiles
# --------------------------------------------------------------------------------------


class _SpecifiedUserResolves(Collection[str]):
    pass


class _UserLockfileRequests(Collection[PythonLockfileRequest]):
    pass


@rule
async def setup_user_lockfile_requests(
    requested: _SpecifiedUserResolves, all_targets: AllTargets, python_setup: PythonSetup
) -> _UserLockfileRequests:
    # First, associate all resolves with their consumers.
    resolves_to_roots = defaultdict(list)
    for tgt in all_targets:
        if not tgt.has_field(PythonResolveField):
            continue
        tgt[PythonResolveField].validate(python_setup)
        resolve = tgt[PythonResolveField].value
        if resolve is None:
            continue
        resolves_to_roots[resolve].append(tgt.address)

    # Expand the resolves for all specified.
    transitive_targets_per_resolve = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest(resolves_to_roots[resolve]))
        for resolve in requested
    )
    pex_requirements_per_resolve = []
    interpreter_constraints_per_resolve = []
    for transitive_targets in transitive_targets_per_resolve:
        req_fields = []
        ic_fields = []
        for tgt in transitive_targets.closure:
            if tgt.has_field(PythonRequirementsField):
                req_fields.append(tgt[PythonRequirementsField])
            if tgt.has_field(InterpreterConstraintsField):
                ic_fields.append(tgt[InterpreterConstraintsField])
        pex_requirements_per_resolve.append(
            PexRequirements.create_from_requirement_fields(req_fields)
        )
        interpreter_constraints_per_resolve.append(
            InterpreterConstraints.create_from_compatibility_fields(ic_fields, python_setup)
        )

    requests = (
        PythonLockfileRequest(
            requirements.req_strings,
            interpreter_constraints,
            resolve_name=resolve,
            lockfile_dest=python_setup.resolves_to_lockfiles[resolve],
        )
        for resolve, requirements, interpreter_constraints in zip(
            requested, pex_requirements_per_resolve, interpreter_constraints_per_resolve
        )
    )
    return _UserLockfileRequests(requests)


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
    python_setup: PythonSetup,
    python_repos: PythonRepos,
) -> GenerateLockfilesGoal:
    if python_repos.repos:
        warn_python_repos("repos")
    if python_repos.indexes != [python_repos.pypi_index]:
        warn_python_repos("indexes")

    specified_user_resolves, specified_tool_sentinels = determine_resolves_to_generate(
        python_setup.resolves_to_lockfiles.keys(),
        union_membership[PythonToolLockfileSentinel],
        generate_lockfiles_subsystem.resolve_names,
    )

    specified_user_requests = await Get(
        _UserLockfileRequests, _SpecifiedUserResolves(specified_user_resolves)
    )
    specified_tool_requests = await MultiGet(
        Get(PythonLockfileRequest, PythonToolLockfileSentinel, sentinel())
        for sentinel in specified_tool_sentinels
    )
    applicable_tool_requests = filter_tool_lockfile_requests(
        specified_tool_requests,
        resolve_specified=bool(generate_lockfiles_subsystem.resolve_names),
    )

    results = await MultiGet(
        Get(PythonLockfile, PythonLockfileRequest, req)
        for req in (*specified_user_requests, *applicable_tool_requests)
    )

    merged_digest = await Get(Digest, MergeDigests(res.digest for res in results))
    workspace.write_digest(merged_digest)
    for result in results:
        logger.info(f"Wrote lockfile for the resolve `{result.resolve_name}` to {result.path}")

    return GenerateLockfilesGoal(exit_code=0)


def warn_python_repos(option: str) -> None:
    logger.warning(
        f"The option `[python-repos].{option}` is configured, but it does not currently work "
        "with lockfile generation. Lockfile generation will fail if the relevant requirements "
        "cannot be located on PyPI.\n\n"
        "If lockfile generation fails, you can disable lockfiles by setting "
        "`[tool].lockfile = '<none>'`, e.g. setting `[black].lockfile`. You can also manually "
        "generate a lockfile, such as by using pip-compile or `pip freeze`. Set the "
        "`[tool].lockfile` option to the path you manually generated. When manually maintaining "
        "lockfiles, set `[python].invalid_lockfile_behavior = 'ignore'."
    )


class AmbiguousResolveNamesError(Exception):
    def __init__(self, ambiguous_names: list[str]) -> None:
        if len(ambiguous_names) == 1:
            first_paragraph = (
                "A resolve name from the option "
                "`[python].experimental_resolves_to_lockfiles` collides with the name of a "
                f"tool resolve: {ambiguous_names[0]}"
            )
        else:
            first_paragraph = (
                "Some resolve names from the option "
                "`[python].experimental_resolves_to_lockfiles` collide with the names of "
                f"tool resolves: {sorted(ambiguous_names)}"
            )
        super().__init__(
            f"{first_paragraph}\n\n"
            "To fix, please update `[python].experimental_resolves_to_lockfiles` to use "
            "different resolve names."
        )


def determine_resolves_to_generate(
    all_user_resolves: Iterable[str],
    all_tool_sentinels: Iterable[type[PythonToolLockfileSentinel]],
    requested_resolve_names: Sequence[str],
) -> tuple[list[str], list[type[PythonToolLockfileSentinel]]]:
    """Apply the `--resolve` option to determine which resolves are specified.

    Return a tuple of `(user_resolves, tool_lockfile_sentinels)`.
    """
    resolve_names_to_sentinels = {
        sentinel.options_scope: sentinel for sentinel in all_tool_sentinels
    }

    ambiguous_resolve_names = [
        resolve_name
        for resolve_name in all_user_resolves
        if resolve_name in resolve_names_to_sentinels
    ]
    if ambiguous_resolve_names:
        raise AmbiguousResolveNamesError(ambiguous_resolve_names)

    if not requested_resolve_names:
        return list(all_user_resolves), list(all_tool_sentinels)

    specified_user_resolves = []
    specified_sentinels = []
    unrecognized_resolve_names = []
    for resolve_name in requested_resolve_names:
        sentinel = resolve_names_to_sentinels.get(resolve_name)
        if sentinel:
            specified_sentinels.append(sentinel)
        elif resolve_name in all_user_resolves:
            specified_user_resolves.append(resolve_name)
        else:
            unrecognized_resolve_names.append(resolve_name)

    if unrecognized_resolve_names:
        raise UnrecognizedResolveNamesError(
            unrecognized_resolve_names,
            {*all_user_resolves, *resolve_names_to_sentinels.keys()},
            description_of_origin="the option `--generate-lockfiles-resolve`",
        )

    return specified_user_resolves, specified_sentinels


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
