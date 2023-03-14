# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os.path
from collections import defaultdict
from dataclasses import dataclass
from operator import itemgetter
from typing import Iterable

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonRequirementResolveField, PythonRequirementsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_diff import _generate_python_lockfile_diff
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadata
from pants.backend.python.util_rules.pex_cli import PexCliProcess
from pants.backend.python.util_rules.pex_requirements import (  # noqa: F401
    GeneratePythonToolLockfileSentinel as GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.util_rules.pex_requirements import (
    PexRequirements,
    ResolvePexConfig,
    ResolvePexConfigRequest,
)
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
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent, MergeDigests
from pants.engine.internals.synthetic_targets import SyntheticAddressMaps, SyntheticTargetsRequest
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.process import ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import AllTargets
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class GeneratePythonLockfile(GenerateLockfile):
    requirements: FrozenOrderedSet[str]
    interpreter_constraints: InterpreterConstraints

    @classmethod
    def from_tool(
        cls,
        subsystem: PythonToolRequirementsBase,
        interpreter_constraints: InterpreterConstraints | None = None,
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
                diff=False,
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
            diff=False,
        )

    @property
    def requirements_hex_digest(self) -> str:
        """Produces a hex digest of the requirements input for this lockfile."""
        return calculate_invalidation_digest(self.requirements)


@rule
def wrap_python_lockfile_request(request: GeneratePythonLockfile) -> WrappedGenerateLockfile:
    return WrappedGenerateLockfile(request)


@dataclass(frozen=True)
class _PipArgsAndConstraintsSetup:
    resolve_config: ResolvePexConfig
    args: tuple[str, ...]
    digest: Digest


async def _setup_pip_args_and_constraints_file(resolve_name: str) -> _PipArgsAndConstraintsSetup:
    resolve_config = await Get(ResolvePexConfig, ResolvePexConfigRequest(resolve_name))

    args = list(resolve_config.pex_args())
    digests = []

    if resolve_config.no_binary or resolve_config.only_binary:
        pip_args_file = "__pip_args.txt"
        args.extend(["-r", pip_args_file])
        pip_args_file_content = "\n".join(
            [f"--no-binary {pkg}" for pkg in resolve_config.no_binary]
            + [f"--only-binary {pkg}" for pkg in resolve_config.only_binary]
        )
        pip_args_digest = await Get(
            Digest, CreateDigest([FileContent(pip_args_file, pip_args_file_content.encode())])
        )
        digests.append(pip_args_digest)

    if resolve_config.constraints_file:
        args.append(f"--constraints={resolve_config.constraints_file.path}")
        digests.append(resolve_config.constraints_file.digest)

    input_digest = await Get(Digest, MergeDigests(digests))
    return _PipArgsAndConstraintsSetup(resolve_config, tuple(args), input_digest)


@rule(desc="Generate Python lockfile", level=LogLevel.DEBUG)
async def generate_lockfile(
    req: GeneratePythonLockfile,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
    python_setup: PythonSetup,
) -> GenerateLockfileResult:
    pip_args_setup = await _setup_pip_args_and_constraints_file(req.resolve_name)

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
                "--pip-version",
                python_setup.pip_version.value,
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
                *pip_args_setup.args,
                *req.interpreter_constraints.generate_pex_arg_list(),
                *req.requirements,
            ),
            additional_input_digest=pip_args_setup.digest,
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

    initial_lockfile_digest_contents = await Get(DigestContents, Digest, result.output_digest)
    metadata = PythonLockfileMetadata.new(
        valid_for_interpreter_constraints=req.interpreter_constraints,
        requirements={
            PipRequirement.parse(
                i,
                description_of_origin=f"the lockfile {req.lockfile_dest} for the resolve {req.resolve_name}",
            )
            for i in req.requirements
        },
        manylinux=pip_args_setup.resolve_config.manylinux,
        requirement_constraints=(
            set(pip_args_setup.resolve_config.constraints_file.constraints)
            if pip_args_setup.resolve_config.constraints_file
            else set()
        ),
        only_binary=set(pip_args_setup.resolve_config.only_binary),
        no_binary=set(pip_args_setup.resolve_config.no_binary),
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

    if req.diff:
        diff = await _generate_python_lockfile_diff(
            final_lockfile_digest, req.resolve_name, req.lockfile_dest
        )
    else:
        diff = None

    return GenerateLockfileResult(final_lockfile_digest, req.resolve_name, req.lockfile_dest, diff)


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
            requirements=PexRequirements.req_strings_from_requirement_fields(
                resolve_to_requirements_fields[resolve]
            ),
            interpreter_constraints=InterpreterConstraints(
                python_setup.resolves_to_interpreter_constraints.get(
                    resolve, python_setup.interpreter_constraints
                )
            ),
            resolve_name=resolve,
            lockfile_dest=python_setup.resolves[resolve],
            diff=False,
        )
        for resolve in requested
    )


@dataclass(frozen=True)
class PythonSyntheticLockfileTargetsRequest(SyntheticTargetsRequest):
    """Register the type used to create synthetic targets for Python lockfiles.

    As the paths for all lockfiles are known up-front, we set the `path` field to
    `SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS` so that we get a single request for all
    our synthetic targets rather than one request per directory.
    """

    path: str = SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS


def synthetic_lockfile_target_name(resolve: str) -> str:
    return f"_{resolve}_lockfile"


@rule
async def python_lockfile_synthetic_targets(
    request: PythonSyntheticLockfileTargetsRequest,
    python_setup: PythonSetup,
) -> SyntheticAddressMaps:
    if not python_setup.enable_synthetic_lockfiles:
        return SyntheticAddressMaps()

    resolves = [
        (os.path.dirname(lockfile), os.path.basename(lockfile), name)
        for name, lockfile in python_setup.resolves.items()
    ]
    return SyntheticAddressMaps.for_targets_request(
        request,
        [
            (
                os.path.join(spec_path, "BUILD.python-lockfiles"),
                tuple(
                    TargetAdaptor(
                        "_lockfiles", name=synthetic_lockfile_target_name(name), sources=[lockfile]
                    )
                    for _, lockfile, name in lockfiles
                ),
            )
            for spec_path, lockfiles in itertools.groupby(sorted(resolves), key=itemgetter(0))
        ],
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateLockfile, GeneratePythonLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownPythonUserResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedPythonUserResolveNames),
        UnionRule(SyntheticTargetsRequest, PythonSyntheticLockfileTargetsRequest),
    )
