# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os.path
from collections import defaultdict
from dataclasses import dataclass
from operator import itemgetter

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup, Resolver
from pants.backend.python.subsystems.uv import DownloadedUv
from pants.backend.python.target_types import (
    PythonRequirementFindLinksField,
    PythonRequirementResolveField,
    PythonRequirementsField,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_diff import _generate_lockfile_diff
from pants.backend.python.util_rules.lockfile_metadata import LockfileFormat, PythonLockfileMetadata
from pants.backend.python.util_rules.pex import (
    CompletePlatforms,
    digest_complete_platform_addresses,
    find_interpreter,
)
from pants.backend.python.util_rules.pex_cli import PexCliProcess, maybe_log_pex_stderr
from pants.backend.python.util_rules.pex_environment import PexSubsystem
from pants.backend.python.util_rules.pex_requirements import (
    PexRequirements,
    ResolveConfig,
    ResolveConfigRequest,
    determine_resolve_config,
)
from pants.backend.python.util_rules.uv import UvEnvironment, generate_pyproject_toml
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.goals.generate_lockfiles import (
    DEFAULT_TOOL_LOCKFILE,
    GenerateLockfile,
    GenerateLockfileResult,
    GenerateLockfilesSubsystem,
    KnownUserResolveNames,
    KnownUserResolveNamesRequest,
    RequestedUserResolveNames,
    UserGenerateLockfiles,
)
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.lockfile_metadata import calculate_invalidation_digest
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import (
    CreateDigest,
    Digest,
    FileContent,
    GlobExpansionConjunction,
    MergeDigests,
    PathGlobs,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.synthetic_targets import SyntheticAddressMaps, SyntheticTargetsRequest
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.intrinsics import (
    create_digest,
    get_digest_contents,
    merge_digests,
    path_globs_to_digest,
)
from pants.engine.process import Process, ProcessCacheScope, execute_process_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import AllTargets
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.subsystem import _construct_subsystem
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.pip_requirement import PipRequirement


@dataclass(frozen=True)
class GeneratePexLockfile(GenerateLockfile):
    requirements: FrozenOrderedSet[str]
    find_links: FrozenOrderedSet[str]
    interpreter_constraints: InterpreterConstraints
    lock_style: str
    complete_platforms: tuple[str, ...]

    @property
    def requirements_hex_digest(self) -> str:
        """Produces a hex digest of the requirements input for this lockfile."""
        return calculate_invalidation_digest(self.requirements)


@dataclass(frozen=True)
class GenerateUvLockfile(GenerateLockfile):
    requirements: FrozenOrderedSet[str]
    find_links: FrozenOrderedSet[str]
    interpreter_constraints: InterpreterConstraints

    @property
    def requirements_hex_digest(self) -> str:
        """Produces a hex digest of the requirements input for this lockfile."""
        return calculate_invalidation_digest(self.requirements)


@dataclass(frozen=True)
class _PipArgsAndConstraintsSetup:
    resolve_config: ResolveConfig
    args: tuple[str, ...]
    digest: Digest


async def _setup_pip_args_and_constraints_file(resolve_name: str) -> _PipArgsAndConstraintsSetup:
    resolve_config = await determine_resolve_config(
        ResolveConfigRequest(resolve_name), **implicitly()
    )

    args = list(resolve_config.pex_args())
    digests: list[Digest] = []

    if resolve_config.constraints_file:
        args.append(f"--constraints={resolve_config.constraints_file.path}")
        digests.append(resolve_config.constraints_file.digest)

    input_digest = await merge_digests(MergeDigests(digests))
    return _PipArgsAndConstraintsSetup(resolve_config, tuple(args), input_digest)


@rule(desc="Generate Pex lockfile", level=LogLevel.DEBUG)
async def generate_pex_lockfile(
    req: GeneratePexLockfile,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
    python_setup: PythonSetup,
    pex_subsystem: PexSubsystem,
) -> GenerateLockfileResult:
    if not req.requirements:
        raise ValueError(
            f"Cannot generate lockfile with no requirements. Please add some requirements to {req.resolve_name}."
        )

    pip_args_setup = await _setup_pip_args_and_constraints_file(req.resolve_name)
    header_delimiter = "//"

    python = await find_interpreter(req.interpreter_constraints, **implicitly())

    # Resolve complete platform targets if specified
    complete_platforms: CompletePlatforms | None = None
    if req.complete_platforms:
        # Resolve target addresses to get platform JSON files
        complete_platforms = await digest_complete_platform_addresses(
            UnparsedAddressInputs(
                req.complete_platforms,
                owning_address=None,
                description_of_origin=f"the `[python].resolves_to_complete_platforms` for resolve `{req.resolve_name}`",
            )
        )

    # Add complete platforms if specified, otherwise use default target systems for universal locks
    if complete_platforms:
        target_system_args = tuple(
            f"--complete-platform={platform}" for platform in complete_platforms
        )
    elif req.lock_style == "universal":
        # PEX files currently only run on Linux and Mac machines; so we hard code this
        # limit on lock universality to avoid issues locking due to irrelevant
        # Windows-only dependency issues. See this Pex issue that originated from a
        # Pants user issue presented in Slack:
        #   https://github.com/pex-tool/pex/issues/1821
        #
        # Note: --target-system only applies to universal locks. For other lock styles
        # (strict, sources) without complete platforms, we don't specify platform args
        # and PEX will lock for the current platform only.
        target_system_args = (
            "--target-system",
            "linux",
            "--target-system",
            "mac",
        )
    else:
        # For non-universal lock styles without complete platforms, don't specify
        # platform arguments - PEX will lock for the current platform only
        target_system_args = ()

    if generate_lockfiles_subsystem.sync:
        existing_lockfile_digest = await path_globs_to_digest(
            PathGlobs(
                globs=(req.lockfile_dest,),
                # We ignore errors, since the lockfile may not exist.
                glob_match_error_behavior=GlobMatchErrorBehavior.ignore,
                conjunction=GlobExpansionConjunction.any_match,
            )
        )
    else:
        existing_lockfile_digest = EMPTY_DIGEST

    output_flag = "--lock" if generate_lockfiles_subsystem.sync else "--output"
    result = await execute_process_or_raise(
        **implicitly(
            PexCliProcess(
                subcommand=("lock", "sync" if generate_lockfiles_subsystem.sync else "create"),
                extra_args=(
                    f"{output_flag}={req.lockfile_dest}",
                    f"--style={req.lock_style}",
                    "--pip-version",
                    python_setup.pip_version,
                    "--resolver-version",
                    "pip-2020-resolver",
                    "--preserve-pip-download-log",
                    "pex-pip-download.log",
                    *target_system_args,
                    # This makes diffs more readable when lockfiles change.
                    "--indent=2",
                    f"--python-path={python.path}",
                    *(f"--find-links={link}" for link in req.find_links),
                    *pip_args_setup.args,
                    # When complete platforms are specified, don't pass interpreter constraints.
                    # The complete platforms already define Python versions and platforms.
                    # Passing both causes PEX to generate duplicate locked_requirements entries
                    # when the local platform matches a complete platform.
                    # TODO(#9560): Consider validating that these platforms are valid with the
                    #  interpreter constraints.
                    *(
                        req.interpreter_constraints.generate_pex_arg_list()
                        if not complete_platforms
                        else ()
                    ),
                    *(
                        f"--override={override}"
                        for override in pip_args_setup.resolve_config.overrides
                    ),
                    *req.requirements,
                ),
                additional_input_digest=await merge_digests(
                    MergeDigests(
                        [existing_lockfile_digest, pip_args_setup.digest]
                        + ([complete_platforms.digest] if complete_platforms else [])
                    )
                ),
                output_files=(req.lockfile_dest,),
                description=f"Generate pex lockfile for {req.resolve_name}",
                # Instead of caching lockfile generation with LMDB, we instead use the invalidation
                # scheme from `lockfile_metadata.py` to check for stale/invalid lockfiles. This is
                # necessary so that our invalidation is resilient to deleting LMDB or running on a
                # new machine.
                #
                # We disable persistent caching so that when you generate a lockfile, you always get
                # the most up-to-date snapshot of the world. This is generally desirable and also
                # necessary to avoid an awkward edge case where different developers generate
                # different lockfiles even when generating at the same time. See
                # https://github.com/pantsbuild/pants/issues/12591.
                cache_scope=ProcessCacheScope.PER_SESSION,
            )
        )
    )
    maybe_log_pex_stderr(result.stderr, pex_subsystem.verbosity)

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
        excludes=set(pip_args_setup.resolve_config.excludes),
        overrides=set(pip_args_setup.resolve_config.overrides),
        sources=set(pip_args_setup.resolve_config.sources),
        lock_style=req.lock_style,
        complete_platforms=req.complete_platforms,
        uploaded_prior_to=pip_args_setup.resolve_config.uploaded_prior_to,
        lockfile_format=LockfileFormat.PEX,
        resolve=req.resolve_name,
    )
    regenerate_command = (
        generate_lockfiles_subsystem.custom_command
        or f"{bin_name()} generate-lockfiles --resolve={req.resolve_name}"
    )
    if python_setup.separate_lockfile_metadata_file:
        descr = f"This lockfile was generated by Pants. To regenerate, run: {regenerate_command}"
        metadata_digest = await create_digest(
            CreateDigest(
                [
                    FileContent(
                        PythonLockfileMetadata.metadata_location_for_lockfile(req.lockfile_dest),
                        metadata.to_json(with_description=descr).encode(),
                    ),
                ]
            )
        )
        final_lockfile_digest = await merge_digests(
            MergeDigests([metadata_digest, result.output_digest])
        )
    else:
        initial_lockfile_digest_contents = await get_digest_contents(result.output_digest)
        lockfile_with_header = metadata.add_header_to_lockfile(
            initial_lockfile_digest_contents[0].content,
            regenerate_command=regenerate_command,
            delimeter=header_delimiter,
        )
        final_lockfile_digest = await create_digest(
            CreateDigest(
                [
                    FileContent(req.lockfile_dest, lockfile_with_header),
                ]
            )
        )

    if req.diff:
        diff = await _generate_lockfile_diff(
            final_lockfile_digest, req.resolve_name, req.lockfile_dest, LockfileFormat.PEX
        )
    else:
        diff = None

    return GenerateLockfileResult(final_lockfile_digest, req.resolve_name, req.lockfile_dest, diff)


@rule(desc="Generate uv lockfile", level=LogLevel.DEBUG)
async def generate_uv_lockfile(
    req: GenerateUvLockfile,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
    downloaded_uv: DownloadedUv,
    uv_env: UvEnvironment,
) -> GenerateLockfileResult:
    if not req.interpreter_constraints:
        raise ValueError(
            f"Cannot generate uv lockfile for resolve {req.resolve_name} with no interpreter "
            "constraints. Please set `interpreter_constraints` for this resolve."
        )

    resolve_config = await determine_resolve_config(
        ResolveConfigRequest(req.resolve_name), **implicitly()
    )
    resolve_config.validate_for_uv(req.resolve_name)

    pyproject_content = generate_pyproject_toml(
        req.resolve_name, req.interpreter_constraints, req.requirements
    )

    if generate_lockfiles_subsystem.sync:
        # `uv lock` does a minimal update by default if an existing lockfile is present.
        # So we just need to make sure it is. There are no special flags to specify.
        existing_lockfile_digest = await path_globs_to_digest(
            PathGlobs(
                globs=(req.lockfile_dest,),
                # We ignore errors, since the lockfile may not exist.
                glob_match_error_behavior=GlobMatchErrorBehavior.ignore,
                conjunction=GlobExpansionConjunction.any_match,
            )
        )
    else:
        existing_lockfile_digest = EMPTY_DIGEST

    # uv always writes the lockfile to `uv.lock` in the project directory. We capture that
    # and rename it to req.lockfile_dest in the final digest.
    uv_lock_output = "uv.lock"
    uv_config = resolve_config.uv_config(extra_find_links=req.find_links)

    uv_config_digest = await create_digest(
        CreateDigest(
            [
                FileContent("pyproject.toml", pyproject_content.encode()),
                FileContent("uv.toml", uv_config.encode()),
            ]
        )
    )

    input_digest = await merge_digests(
        MergeDigests([downloaded_uv.digest, uv_config_digest, existing_lockfile_digest])
    )

    result = await execute_process_or_raise(
        **implicitly(
            Process(
                argv=(
                    *downloaded_uv.args(),
                    "lock",
                ),
                env=uv_env.env,
                input_digest=input_digest,
                output_files=(uv_lock_output,),
                append_only_caches=downloaded_uv.append_only_caches(),
                description=f"Generate uv lockfile for {req.resolve_name}",
                # We disable persistent caching so that when you generate a lockfile, you always
                # get the most up-to-date snapshot of the world.
                cache_scope=ProcessCacheScope.PER_SESSION,
            )
        )
    )

    # Rename uv.lock to the configured lockfile destination.
    uv_lock_contents = await get_digest_contents(result.output_digest)
    uv_lock_digest = await create_digest(
        CreateDigest([FileContent(req.lockfile_dest, next(iter(uv_lock_contents)).content)])
    )

    regenerate_command = (
        generate_lockfiles_subsystem.custom_command
        or f"{bin_name()} generate-lockfiles --resolve={req.resolve_name}"
    )
    descr = f"This lockfile was generated by Pants. To regenerate, run: {regenerate_command}"
    metadata = PythonLockfileMetadata.new(
        valid_for_interpreter_constraints=req.interpreter_constraints,
        requirements={
            PipRequirement.parse(
                r,
                description_of_origin=f"the lockfile {req.lockfile_dest} for the resolve {req.resolve_name}",
            )
            for r in req.requirements
        },
        manylinux=None,
        requirement_constraints=set(),
        only_binary=set(resolve_config.only_binary),
        no_binary=set(resolve_config.no_binary),
        excludes=set(),
        overrides=set(),
        sources=set(),
        lock_style="universal",
        complete_platforms=(),
        uploaded_prior_to=resolve_config.uploaded_prior_to,
        lockfile_format=LockfileFormat.UV,
        resolve=req.resolve_name,
    )
    metadata_digest = await create_digest(
        CreateDigest(
            [
                FileContent(
                    PythonLockfileMetadata.metadata_location_for_lockfile(req.lockfile_dest),
                    metadata.to_json(with_description=descr).encode(),
                ),
            ]
        )
    )
    final_lockfile_digest = await merge_digests(MergeDigests([metadata_digest, uv_lock_digest]))

    if req.diff:
        diff = await _generate_lockfile_diff(
            final_lockfile_digest, req.resolve_name, req.lockfile_dest, LockfileFormat.UV
        )
    else:
        diff = None

    return GenerateLockfileResult(final_lockfile_digest, req.resolve_name, req.lockfile_dest, diff)


class RequestedPythonUserResolveNames(RequestedUserResolveNames):
    pass


class KnownPythonUserResolveNamesRequest(KnownUserResolveNamesRequest):
    pass


@rule
async def determine_python_user_resolves(
    _: KnownPythonUserResolveNamesRequest,
    python_setup: PythonSetup,
    union_membership: UnionMembership,
) -> KnownUserResolveNames:
    """Find all know Python resolves, from both user-created resolves and internal tools."""
    python_tool_resolves = ExportableTool.filter_for_subclasses(union_membership, PythonToolBase)

    tools_using_default_resolve = [
        resolve_name
        for resolve_name, subsystem_cls in python_tool_resolves.items()
        if (await _construct_subsystem(subsystem_cls)).install_from_resolve is None
    ]

    return KnownUserResolveNames(
        names=(
            *python_setup.resolves.keys(),
            *tools_using_default_resolve,
        ),  # the order of the keys doesn't matter since shadowing is done in `setup_user_lockfile_requests`
        option_name="[python].resolves",
        requested_resolve_names_cls=RequestedPythonUserResolveNames,
    )


@rule
async def setup_user_lockfile_requests(
    requested: RequestedPythonUserResolveNames,
    all_targets: AllTargets,
    python_setup: PythonSetup,
    union_membership: UnionMembership,
) -> UserGenerateLockfiles:
    """Transform the names of resolves requested into the appropriate lockfile request object.

    Shadowing is done here by only checking internal resolves if the resolve is not a user-created
    resolve.
    """
    if not (python_setup.enable_resolves and python_setup.resolves_generate_lockfiles):
        return UserGenerateLockfiles()

    resolve_to_requirements_fields = defaultdict(set)
    resolve_to_find_links: dict[str, set[str]] = defaultdict(set)
    for tgt in all_targets:
        if not tgt.has_fields((PythonRequirementResolveField, PythonRequirementsField)):
            continue
        resolve = tgt[PythonRequirementResolveField].normalized_value(python_setup)
        resolve_to_requirements_fields[resolve].add(tgt[PythonRequirementsField])
        resolve_to_find_links[resolve].update(tgt[PythonRequirementFindLinksField].value or ())

    tools = ExportableTool.filter_for_subclasses(union_membership, PythonToolBase)

    out: set[GenerateLockfile] = set()
    for resolve in requested:
        if resolve in python_setup.resolves:
            requirements = PexRequirements.req_strings_from_requirement_fields(
                resolve_to_requirements_fields[resolve]
            )
            find_links = FrozenOrderedSet(resolve_to_find_links[resolve])
            interpreter_constraints = InterpreterConstraints(
                python_setup.resolves_to_interpreter_constraints.get(
                    resolve, python_setup.interpreter_constraints
                )
            )
            lockfile_dest = python_setup.resolves[resolve]
            if python_setup.resolver == Resolver.uv:
                out.add(
                    GenerateUvLockfile(
                        requirements=requirements,
                        find_links=find_links,
                        interpreter_constraints=interpreter_constraints,
                        resolve_name=resolve,
                        lockfile_dest=lockfile_dest,
                        diff=False,
                    )
                )
            else:
                out.add(
                    GeneratePexLockfile(
                        requirements=requirements,
                        find_links=find_links,
                        interpreter_constraints=interpreter_constraints,
                        resolve_name=resolve,
                        lockfile_dest=lockfile_dest,
                        diff=False,
                        lock_style=python_setup.resolves_to_lock_style().get(resolve, "universal"),
                        complete_platforms=tuple(
                            python_setup.resolves_to_complete_platforms().get(resolve, [])
                        ),
                    )
                )
        else:
            tool_cls: type[PythonToolBase] = tools[resolve]
            tool = await _construct_subsystem(tool_cls)

            # TODO: we shouldn't be managing default ICs in lockfile identification.
            #   We should find a better place to do this or a better way to default
            if tool.register_interpreter_constraints:
                ic = tool.interpreter_constraints
            else:
                ic = InterpreterConstraints(tool.default_interpreter_constraints)

            if python_setup.resolver == Resolver.uv:
                out.add(
                    GenerateUvLockfile(
                        requirements=FrozenOrderedSet(sorted(tool.requirements)),
                        find_links=FrozenOrderedSet(),
                        interpreter_constraints=ic,
                        resolve_name=resolve,
                        lockfile_dest=DEFAULT_TOOL_LOCKFILE,
                        diff=False,
                    )
                )
            else:
                out.add(
                    GeneratePexLockfile(
                        requirements=FrozenOrderedSet(sorted(tool.requirements)),
                        find_links=FrozenOrderedSet(),
                        interpreter_constraints=ic,
                        resolve_name=resolve,
                        lockfile_dest=DEFAULT_TOOL_LOCKFILE,
                        diff=False,
                        lock_style="universal",  # Tools always use universal style
                        complete_platforms=(),  # Tools don't use complete platforms
                    )
                )

    return UserGenerateLockfiles(out)


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
                        "_lockfiles",
                        name=synthetic_lockfile_target_name(name),
                        sources=(lockfile,),
                        __description_of_origin__=f"the [python].resolves option {name!r}",
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
        UnionRule(GenerateLockfile, GeneratePexLockfile),
        UnionRule(GenerateLockfile, GenerateUvLockfile),
        UnionRule(KnownUserResolveNamesRequest, KnownPythonUserResolveNamesRequest),
        UnionRule(RequestedUserResolveNames, RequestedPythonUserResolveNames),
        UnionRule(SyntheticTargetsRequest, PythonSyntheticLockfileTargetsRequest),
    )
