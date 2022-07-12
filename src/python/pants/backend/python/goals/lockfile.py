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
    PythonRequirementResolveField,
    PythonRequirementsField,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadata
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_cli import PexCliProcess
from pants.backend.python.util_rules.pex_requirements import PexRequirements
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
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratePythonLockfile(GenerateLockfile):
    requirements: FrozenOrderedSet[str]
    interpreter_constraints: InterpreterConstraints
    use_pex: bool

    @classmethod
    def from_tool(
        cls,
        subsystem: PythonToolRequirementsBase,
        interpreter_constraints: InterpreterConstraints | None = None,
        *,
        use_pex: bool,
        extra_requirements: Iterable[str] = (),
    ) -> GeneratePythonLockfile:
        """Create a request for a dedicated lockfile for the tool.

        If the tool determines its interpreter constraints by using the constraints of user code,
        rather than the option `--interpreter-constraints`, you must pass the arg
        `interpreter_constraints`.
        """
        if not subsystem.uses_custom_lockfile:
            return cls(
                requirements=FrozenOrderedSet(),
                interpreter_constraints=InterpreterConstraints(),
                resolve_name=subsystem.options_scope,
                lockfile_dest=subsystem.lockfile,
                use_pex=use_pex,
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
            use_pex=use_pex,
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


@dataclass(frozen=True)
class MaybeWarnPythonReposRequest:
    pass


@rule
def maybe_warn_python_repos(
    _: MaybeWarnPythonReposRequest, python_repos: PythonRepos
) -> MaybeWarnPythonRepos:
    def warn_python_repos(option: str) -> None:
        logger.warning(
            softwrap(
                f"""
                The option `[python-repos].{option}` is configured, but it does not work when using
                Poetry for lockfile generation. Lockfile generation will fail if the relevant
                requirements cannot be located on PyPI.

                Instead, you can use Pex to generate lockfiles by setting
                `[python].lockfile_generator = 'pex'.

                Alternatively, you can disable lockfiles by setting
                `[tool].lockfile = '<none>'`, e.g. setting `[black].lockfile`. You can also manually
                generate a lockfile, such as by using pip-compile or `pip freeze`. Set the
                `[tool].lockfile` option to the path you manually generated. When manually
                maintaining lockfiles, set `[python].invalid_lockfile_behavior = 'ignore'. For user
                lockfiles from `[python].resolves`, set
                `[python].resolves_generate_lockfiles = false`.
                """
            )
        )

    if python_repos.repos:
        warn_python_repos("repos")
    if python_repos.indexes != (python_repos.pypi_index,):
        warn_python_repos("indexes")
    return MaybeWarnPythonRepos()


@rule(desc="Generate Python lockfile", level=LogLevel.DEBUG)
async def generate_lockfile(
    req: GeneratePythonLockfile,
    poetry_subsystem: PoetrySubsystem,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
    python_repos: PythonRepos,
    python_setup: PythonSetup,
) -> GenerateLockfileResult:
    if req.use_pex:
        pip_args_file = "__pip_args.txt"
        pip_args_file_content = "\n".join(
            [f"--no-binary {pkg}" for pkg in python_setup.no_binary]
            + [f"--only-binary {pkg}" for pkg in python_setup.only_binary]
        )
        pip_args_file_digest = await Get(
            Digest, CreateDigest([FileContent(pip_args_file, pip_args_file_content.encode())])
        )
        header_delimiter = "//"
        result = await Get(
            ProcessResult,
            PexCliProcess(
                subcommand=("lock", "create"),
                extra_args=(
                    "--output=lock.json",
                    "--no-emit-warnings",
                    # See https://github.com/pantsbuild/pants/issues/12458. For now, we always
                    # generate universal locks because they have the best compatibility. We may
                    # want to let users change this, as `style=strict` is safer.
                    "--style=universal",
                    "--resolver-version",
                    "pip-2020-resolver",
                    # PEX files currently only run on Linux and Mac machines; so we hard code this
                    # limit on lock universaility to avoid issues locking due to irrelevant
                    # Windows-only dependency issues. See this Pex issue that originated from a
                    # Pants user issue presented in Slack:
                    #   https://github.com/pantsbuild/pex/issues/1821
                    #
                    # At some point it will probably make sense to expose `--target-system` for
                    # configuration.
                    "--target-system",
                    "linux",
                    "--target-system",
                    "mac",
                    # This makes diffs more readable when lockfiles change.
                    "--indent=2",
                    "-r",
                    pip_args_file,
                    *python_repos.pex_args,
                    *python_setup.manylinux_pex_args,
                    *req.interpreter_constraints.generate_pex_arg_list(),
                    *req.requirements,
                ),
                additional_input_digest=pip_args_file_digest,
                output_files=("lock.json",),
                description=f"Generate lockfile for {req.resolve_name}",
                # Instead of caching lockfile generation with LMDB, we instead use the invalidation
                # scheme from `lockfile_metadata.py` to check for stale/invalid lockfiles. This is
                # necessary so that our invalidation is resilient to deleting LMDB or running on a
                # new machine.
                #
                # We disable caching with LMDB so that when you generate a lockfile, you always get
                # the most up-to-date snapshot of the world. This is generally desirable and also
                # necessary to avoid an awkward edge case where different developers generate
                # different lockfiles even when generating at the same time. See
                # https://github.com/pantsbuild/pants/issues/12591.
                cache_scope=ProcessCacheScope.PER_SESSION,
            ),
        )
    else:
        header_delimiter = "#"
        await Get(MaybeWarnPythonRepos, MaybeWarnPythonReposRequest())
        _pyproject_toml = create_pyproject_toml(
            req.requirements, req.interpreter_constraints
        ).encode()
        _pyproject_toml_digest, _launcher_digest = await MultiGet(
            Get(Digest, CreateDigest([FileContent("pyproject.toml", _pyproject_toml)])),
            Get(Digest, CreateDigest([POETRY_LAUNCHER])),
        )

        _poetry_pex = await Get(
            VenvPex,
            PexRequest,
            poetry_subsystem.to_pex_request(
                main=EntryPoint(PurePath(POETRY_LAUNCHER.path).stem), sources=_launcher_digest
            ),
        )

        # WONTFIX(#12314): Wire up Poetry to named_caches.
        # WONTFIX(#12314): Wire up all the pip options like indexes.
        _lock_result = await Get(
            ProcessResult,
            VenvPexProcess(
                _poetry_pex,
                argv=("lock",),
                input_digest=_pyproject_toml_digest,
                output_files=("poetry.lock", "pyproject.toml"),
                description=f"Generate lockfile for {req.resolve_name}",
                cache_scope=ProcessCacheScope.PER_SESSION,
            ),
        )
        result = await Get(
            ProcessResult,
            VenvPexProcess(
                _poetry_pex,
                argv=("export", "-o", req.lockfile_dest),
                input_digest=_lock_result.output_digest,
                output_files=(req.lockfile_dest,),
                description=(
                    f"Exporting Poetry lockfile to requirements.txt format for {req.resolve_name}"
                ),
                level=LogLevel.DEBUG,
            ),
        )

    initial_lockfile_digest_contents = await Get(DigestContents, Digest, result.output_digest)
    # TODO(#12314) Improve error message on `Requirement.parse`
    metadata = PythonLockfileMetadata.new(
        req.interpreter_constraints,
        {PipRequirement.parse(i) for i in req.requirements},
    )
    lockfile_with_header = metadata.add_header_to_lockfile(
        initial_lockfile_digest_contents[0].content,
        regenerate_command=(
            generate_lockfiles_subsystem.custom_command
            or f"{bin_name()} generate-lockfiles --resolve={req.resolve_name}"
        ),
        delimeter=header_delimiter,
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
        option_name="[python].resolves",
        requested_resolve_names_cls=RequestedPythonUserResolveNames,
    )


@rule
async def setup_user_lockfile_requests(
    requested: RequestedPythonUserResolveNames, all_targets: AllTargets, python_setup: PythonSetup
) -> UserGenerateLockfiles:
    if not (python_setup.enable_resolves and python_setup.resolves_generate_lockfiles):
        return UserGenerateLockfiles()

    resolve_to_requirements_fields = defaultdict(set)
    for tgt in all_targets:
        if not tgt.has_fields((PythonRequirementResolveField, PythonRequirementsField)):
            continue
        resolve = tgt[PythonRequirementResolveField].normalized_value(python_setup)
        resolve_to_requirements_fields[resolve].add(tgt[PythonRequirementsField])

    return UserGenerateLockfiles(
        GeneratePythonLockfile(
            requirements=PexRequirements.create_from_requirement_fields(
                resolve_to_requirements_fields[resolve],
                constraints_strings=(),
            ).req_strings,
            interpreter_constraints=InterpreterConstraints(
                python_setup.resolves_to_interpreter_constraints.get(
                    resolve, python_setup.interpreter_constraints
                )
            ),
            resolve_name=resolve,
            lockfile_dest=python_setup.resolves[resolve],
            use_pex=python_setup.generate_lockfiles_with_pex,
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
