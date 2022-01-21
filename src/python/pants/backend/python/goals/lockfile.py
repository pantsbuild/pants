# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.poetry import (
    POETRY_LAUNCHER,
    PoetrySubsystem,
    create_pyproject_toml,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.repos import PythonRepos
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    EntryPoint,
    PythonRequirementCompatibleResolvesField,
    PythonRequirementsField,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadata
from pants.backend.python.util_rules.pex import PexRequest, PexRequirements, VenvPex, VenvPexProcess
from pants.core.goals.generate_lockfiles import (
    GenerateLockfile,
    GenerateLockfileResult,
    GenerateLockfilesSubsystem,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
    WrappedGenerateLockfile,
)
from pants.core.util_rules.lockfile_metadata import calculate_invalidation_digest
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent
from pants.engine.process import ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import AllTargets
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratePythonLockfile(GenerateLockfile):
    requirements: FrozenOrderedSet[str]
    interpreter_constraints: InterpreterConstraints
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
    ) -> GeneratePythonLockfile:
        """Create a request for a dedicated lockfile for the tool.

        If the tool determines its interpreter constraints by using the constraints of user code,
        rather than the option `--interpreter-constraints`, you must pass the arg
        `interpreter_constraints`.
        """
        if not subsystem.uses_lockfile:
            return cls(
                requirements=FrozenOrderedSet(),
                interpreter_constraints=InterpreterConstraints(),
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


@rule
def wrap_python_lockfile_request(request: GeneratePythonLockfile) -> WrappedGenerateLockfile:
    return WrappedGenerateLockfile(request)


class MaybeWarnPythonRepos:
    pass


@rule
def maybe_warn_python_repos(python_repos: PythonRepos) -> MaybeWarnPythonRepos:
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

    if python_repos.repos:
        warn_python_repos("repos")
    if python_repos.indexes != [python_repos.pypi_index]:
        warn_python_repos("indexes")
    return MaybeWarnPythonRepos()


@rule(desc="Generate Python lockfile", level=LogLevel.DEBUG)
async def generate_lockfile(
    req: GeneratePythonLockfile,
    poetry_subsystem: PoetrySubsystem,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
    _: MaybeWarnPythonRepos,
) -> GenerateLockfileResult:
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
    metadata = PythonLockfileMetadata.new(
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
    return GenerateLockfileResult(final_lockfile_digest, req.resolve_name, req.lockfile_dest)


class RequestedPythonUserResolveNames(RequestedUserResolveNames):
    pass


class KnownPythonUserResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


@rule
def determine_python_user_resolves(
    _: KnownPythonUserResolveNamesRequest, python_setup: PythonSetup
) -> KnownUserResolveNames:
    return KnownUserResolveNames(
        names=tuple(python_setup.resolves.keys()),
        option_name="[python].experimental_resolves",
        requested_resolve_names_cls=RequestedPythonUserResolveNames,
    )


@rule
async def setup_user_lockfile_requests(
    requested: RequestedPythonUserResolveNames, all_targets: AllTargets, python_setup: PythonSetup
) -> UserGenerateLockfiles:
    if not python_setup.enable_resolves:
        return UserGenerateLockfiles()

    resolve_to_requirements_fields = defaultdict(set)
    for tgt in all_targets:
        if not tgt.has_field(PythonRequirementCompatibleResolvesField):
            continue
        tgt[PythonRequirementCompatibleResolvesField].validate(python_setup)
        for resolve in tgt[PythonRequirementCompatibleResolvesField].value_or_default(python_setup):
            resolve_to_requirements_fields[resolve].add(tgt[PythonRequirementsField])

    # TODO: Figure out how to determine which interpreter constraints to use for each resolve...
    #  Note that `python_requirement` does not have interpreter constraints, so we either need to
    #  inspect all consumers of that resolve or start to closely couple the resolve with the
    #  interpreter constraints (a "context").

    return UserGenerateLockfiles(
        GeneratePythonLockfile(
            requirements=PexRequirements.create_from_requirement_fields(
                resolve_to_requirements_fields[resolve],
                constraints_strings=(),
            ).req_strings,
            interpreter_constraints=InterpreterConstraints(python_setup.interpreter_constraints),
            resolve_name=resolve,
            lockfile_dest=python_setup.resolves[resolve],
        )
        for resolve in requested
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateLockfile, GeneratePythonLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownPythonUserResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedPythonUserResolveNames),
    )
