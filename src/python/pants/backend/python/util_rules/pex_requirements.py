# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Iterator

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.repos import PythonRepos
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior, PythonSetup
from pants.backend.python.target_types import PythonRequirementsField, parse_requirements_file
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    InvalidPythonLockfileReason,
    PythonLockfileMetadata,
    PythonLockfileMetadataV2,
)
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.lockfile_metadata import InvalidLockfileError, LockfileMetadataValidation
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    GlobMatchErrorBehavior,
    PathGlobs,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership
from pants.util.docutil import bin_name, doc_url
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap

if TYPE_CHECKING:
    from pants.backend.python.util_rules.pex import Pex


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lockfile:
    file_path: str
    file_path_description_of_origin: str
    resolve_name: str
    lockfile_hex_digest: str | None = None


@dataclass(frozen=True)
class LockfileContent:
    file_content: FileContent
    resolve_name: str
    lockfile_hex_digest: str | None = None


@dataclass(frozen=True)
class _ToolLockfileMixin:
    uses_source_plugins: bool
    uses_project_interpreter_constraints: bool


@dataclass(frozen=True)
class ToolDefaultLockfile(LockfileContent, _ToolLockfileMixin):
    pass


@dataclass(frozen=True)
class ToolCustomLockfile(Lockfile, _ToolLockfileMixin):
    pass


@dataclass(frozen=True)
class LoadedLockfile:
    """A lockfile after loading and header stripping.

    Validation is deferred until consumption time, because each consumed subset (in the case of a
    PEX-native lockfile) can be individually validated.
    """

    # The digest of the loaded lockfile (which may not be identical to the input).
    lockfile_digest: Digest
    # The path of the loaded lockfile within the Digest.
    lockfile_path: str
    # The loaded metadata for this lockfile, if any.
    metadata: PythonLockfileMetadata | None = field(hash=False)
    # An estimate of the number of requirements in this lockfile, to be used as a heuristic for
    # available parallelism.
    requirement_estimate: int
    # True if the loaded lockfile is in PEX's native format.
    is_pex_native: bool
    # If !is_pex_native, the lockfile parsed as constraints strings, for use when the lockfile
    # needs to be subsetted (see #15031, ##12222).
    as_constraints_strings: FrozenOrderedSet[str] | None
    # The original file or file content (which may not have identical content to the output
    # `lockfile_digest`).
    original_lockfile: Lockfile | LockfileContent


@dataclass(frozen=True)
class LoadedLockfileRequest:
    """A request to load and validate the content of the given lockfile."""

    lockfile: Lockfile | LockfileContent


def _strip_comments_from_pex_json_lockfile(lockfile_bytes: bytes) -> bytes:
    """Pex does not like the header Pants adds to lockfiles, as it violates JSON.

    Note that we only strip lines starting with `//`, which is all that Pants will ever add. If
    users add their own comments, things will fail.
    """
    return b"\n".join(
        line for line in lockfile_bytes.splitlines() if not line.lstrip().startswith(b"//")
    )


def is_probably_pex_json_lockfile(lockfile_bytes: bytes) -> bool:
    for line in lockfile_bytes.splitlines():
        if line and not line.startswith(b"//"):
            # Note that pip/Pex complain if a requirements.txt style starts with `{`.
            return line.lstrip().startswith(b"{")
    return False


def _pex_lockfile_requirement_count(lockfile_bytes: bytes) -> int:
    # TODO: this is a very naive heuristic that will overcount, and also relies on Pants
    #  setting `--indent` when generating lockfiles. More robust would be parsing the JSON
    #  and getting the len(locked_resolves.locked_requirements.project_name), but we risk
    #  if Pex ever changes its lockfile format.

    num_lines = len(lockfile_bytes.splitlines())
    # These are very naive estimates, and they bias towards overcounting. For example, requirements
    # often are 20+ lines.
    num_lines_for_options = 10
    lines_per_req = 10
    return max((num_lines - num_lines_for_options) // lines_per_req, 2)


@rule
async def load_lockfile(
    request: LoadedLockfileRequest,
    python_setup: PythonSetup,
) -> LoadedLockfile:
    lockfile = request.lockfile
    if isinstance(lockfile, Lockfile):
        synthetic_lock = False
        lockfile_path = lockfile.file_path
        lockfile_digest = await Get(
            Digest,
            PathGlobs(
                [lockfile_path],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=lockfile.file_path_description_of_origin,
            ),
        )
        _digest_contents = await Get(DigestContents, Digest, lockfile_digest)
        lock_bytes = _digest_contents[0].content
    else:
        synthetic_lock = True
        _fc = lockfile.file_content
        lockfile_path, lock_bytes = (_fc.path, _fc.content)
        lockfile_digest = await Get(Digest, CreateDigest([_fc]))

    is_pex_native = is_probably_pex_json_lockfile(lock_bytes)
    if is_pex_native:
        header_delimiter = "//"
        lockfile_digest = await Get(
            Digest,
            CreateDigest(
                [FileContent(lockfile_path, _strip_comments_from_pex_json_lockfile(lock_bytes))]
            ),
        )
        requirement_estimate = _pex_lockfile_requirement_count(lock_bytes)
        constraints_strings = None
    else:
        header_delimiter = "#"
        lock_string = lock_bytes.decode()
        # Note: this is a very naive heuristic. It will overcount because entries often
        # have >1 line due to `--hash`.
        requirement_estimate = len(lock_string.splitlines())
        constraints_strings = FrozenOrderedSet(
            str(req) for req in parse_requirements_file(lock_string, rel_path=lockfile_path)
        )

    metadata: PythonLockfileMetadata | None = None
    if should_validate_metadata(lockfile, python_setup):
        metadata = PythonLockfileMetadata.from_lockfile(
            lock_bytes,
            **(dict() if synthetic_lock else dict(lockfile_path=lockfile_path)),
            resolve_name=lockfile.resolve_name,
            delimeter=header_delimiter,
        )

    return LoadedLockfile(
        lockfile_digest,
        lockfile_path,
        metadata,
        requirement_estimate,
        is_pex_native,
        constraints_strings,
        original_lockfile=lockfile,
    )


@dataclass(frozen=True)
class EntireLockfile:
    """A request to resolve the entire contents of a lockfile.

    This resolution mode is used in a few cases:
    1. for poetry or hand-written lockfiles (which do not support being natively subsetted the
       way that a PEX lockfile can be), in order to build a repository-PEX to subset separately.
    2. for tool lockfiles, which (regardless of format), need to resolve the entire lockfile
       content anyway.
    """

    lockfile: Lockfile | LockfileContent
    # If available, the current complete set of requirement strings that influence this lockfile.
    # Used for metadata validation.
    complete_req_strings: tuple[str, ...] | None = None


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexRequirements:
    """A request to resolve a series of requirements (optionally from a "superset" resolve)."""

    req_strings: FrozenOrderedSet[str]
    constraints_strings: FrozenOrderedSet[str]
    # If these requirements should be resolved as a subset of either a repository PEX, or a
    # PEX-native lockfile, the superset to use. # NB: Use of a lockfile here asserts that the
    # lockfile is PEX-native, because legacy lockfiles do not support subset resolves.
    from_superset: Pex | LoadedLockfile | None

    def __init__(
        self,
        req_strings: Iterable[str] = (),
        *,
        constraints_strings: Iterable[str] = (),
        from_superset: Pex | LoadedLockfile | None = None,
    ) -> None:
        """
        :param req_strings: The requirement strings to resolve.
        :param constraints_strings: Constraints strings to apply during the resolve.
        :param from_superset: An optional superset PEX or lockfile to resolve the req strings from.
        """
        self.req_strings = FrozenOrderedSet(sorted(req_strings))
        self.constraints_strings = FrozenOrderedSet(sorted(constraints_strings))
        if isinstance(from_superset, LoadedLockfile) and not from_superset.is_pex_native:
            raise ValueError(
                softwrap(
                    f"""
                    The lockfile {from_superset.original_lockfile} was not in PEX's
                    native format, and so cannot be directly used as a superset.
                    """
                )
            )
        self.from_superset = from_superset

    @classmethod
    def create_from_requirement_fields(
        cls,
        fields: Iterable[PythonRequirementsField],
        constraints_strings: Iterable[str],
    ) -> PexRequirements:
        field_requirements = {str(python_req) for field in fields for python_req in field.value}
        return PexRequirements(field_requirements, constraints_strings=constraints_strings)

    @classmethod
    def req_strings_from_requirement_fields(
        cls, fields: Iterable[PythonRequirementsField]
    ) -> FrozenOrderedSet[str]:
        """A convenience when you only need the raw requirement strings from fields and don't need
        to consider things like constraints or resolves."""
        return cls.create_from_requirement_fields(fields, constraints_strings=()).req_strings

    def __bool__(self) -> bool:
        return bool(self.req_strings)


# NB: This is defined here so that our rule for ResolvePexConfigRequest -> ResolvePexConfig
# can avoid an import cycle. We re-export this out of goals/lockfile.py.
class GeneratePythonToolLockfileSentinel(GenerateToolLockfileSentinel):
    pass


@dataclass(frozen=True)
class ResolvePexConstraintsFile:
    digest: Digest
    path: str
    constraints: FrozenOrderedSet[PipRequirement]


@dataclass(frozen=True)
class ResolvePexConfig:
    """Configuration from `[python]` that impacts how the resolve is created."""

    indexes: tuple[str, ...]
    find_links: tuple[str, ...]
    manylinux: str | None
    constraints_file: ResolvePexConstraintsFile | None
    only_binary: FrozenOrderedSet[PipRequirement]
    no_binary: FrozenOrderedSet[PipRequirement]
    path_mappings: tuple[str, ...]

    def pex_args(self) -> Iterator[str]:
        """Arguments for Pex for indexes/--find-links, manylinux, and path mappings.

        Does not include arguments for constraints files, --only-binary, and --no-binary, which must
        be set up independently.
        """
        # NB: In setting `--no-pypi`, we rely on the default value of `[python-repos].indexes`
        # including PyPI, which will override `--no-pypi` and result in using PyPI in the default
        # case. Why set `--no-pypi`, then? We need to do this so that
        # `[python-repos].indexes = ['custom_url']` will only point to that index and not include
        # PyPI.
        yield "--no-pypi"
        yield from (f"--index={index}" for index in self.indexes)
        yield from (f"--find-links={repo}" for repo in self.find_links)

        if self.manylinux:
            yield "--manylinux"
            yield self.manylinux
        else:
            yield "--no-manylinux"

        yield from (f"--path-mapping={v}" for v in self.path_mappings)


@dataclass(frozen=True)
class ResolvePexConfigRequest(EngineAwareParameter):
    """Find all configuration from `[python]` that impacts how the resolve is created.

    If `resolve_name` is None, then most per-resolve options will be ignored because there is no way
    for users to configure them. However, some options like `[python-repos].indexes` will still be
    loaded.
    """

    resolve_name: str | None

    def debug_hint(self) -> str:
        return self.resolve_name or "<no resolve>"


@rule
async def determine_resolve_pex_config(
    request: ResolvePexConfigRequest,
    python_setup: PythonSetup,
    python_repos: PythonRepos,
    union_membership: UnionMembership,
) -> ResolvePexConfig:
    if request.resolve_name is None:
        return ResolvePexConfig(
            indexes=python_repos.indexes,
            find_links=python_repos.find_links,
            manylinux=python_setup.manylinux,
            constraints_file=None,
            no_binary=FrozenOrderedSet(),
            only_binary=FrozenOrderedSet(),
            path_mappings=python_repos.path_mappings,
        )

    all_python_tool_resolve_names = tuple(
        sentinel.resolve_name
        for sentinel in union_membership.get(GenerateToolLockfileSentinel)
        if issubclass(sentinel, GeneratePythonToolLockfileSentinel)
    )

    no_binary = (
        python_setup.resolves_to_no_binary(all_python_tool_resolve_names).get(request.resolve_name)
        or []
    )
    only_binary = (
        python_setup.resolves_to_only_binary(all_python_tool_resolve_names).get(
            request.resolve_name
        )
        or []
    )

    constraints_file: ResolvePexConstraintsFile | None = None
    _constraints_file_path = python_setup.resolves_to_constraints_file(
        all_python_tool_resolve_names
    ).get(request.resolve_name)
    if _constraints_file_path:
        _constraints_origin = softwrap(
            f"""
            the option `[python].resolves_to_constraints_file` for the resolve
            '{request.resolve_name}'
            """
        )
        _constraints_path_globs = PathGlobs(
            [_constraints_file_path] if _constraints_file_path else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=_constraints_origin,
        )
        _constraints_digest, _constraints_digest_contents = await MultiGet(
            Get(Digest, PathGlobs, _constraints_path_globs),
            Get(DigestContents, PathGlobs, _constraints_path_globs),
        )

        if len(_constraints_digest_contents) != 1:
            raise ValueError(
                softwrap(
                    f"""
                    Expected only one file from {_constraints_origin}, but matched:
                    {sorted(fc.path for fc in _constraints_digest_contents)}

                    Did you use a glob like `*`?
                    """
                )
            )
        _constraints_file_content = next(iter(_constraints_digest_contents))
        constraints = parse_requirements_file(
            _constraints_file_content.content.decode("utf-8"), rel_path=_constraints_file_path
        )
        constraints_file = ResolvePexConstraintsFile(
            _constraints_digest, _constraints_file_path, FrozenOrderedSet(constraints)
        )

    return ResolvePexConfig(
        indexes=python_repos.indexes,
        find_links=python_repos.find_links,
        manylinux=python_setup.manylinux,
        constraints_file=constraints_file,
        no_binary=FrozenOrderedSet(no_binary),
        only_binary=FrozenOrderedSet(only_binary),
        path_mappings=python_repos.path_mappings,
    )


def should_validate_metadata(
    lockfile: Lockfile | LockfileContent,
    python_setup: PythonSetup,
):
    if python_setup.invalid_lockfile_behavior == InvalidLockfileBehavior.ignore:
        return False
    is_tool = isinstance(lockfile, (ToolCustomLockfile, ToolDefaultLockfile))
    return is_tool or python_setup.resolves_generate_lockfiles


def validate_metadata(
    metadata: PythonLockfileMetadata,
    interpreter_constraints: InterpreterConstraints,
    lockfile: Lockfile | LockfileContent,
    consumed_req_strings: Iterable[str],
    python_setup: PythonSetup,
    resolve_config: ResolvePexConfig,
) -> None:
    """Given interpreter constraints and requirements to be consumed, validate lockfile metadata."""

    # TODO(#12314): Improve the exception if invalid strings
    user_requirements = {PipRequirement.parse(i) for i in consumed_req_strings}
    validation = metadata.is_valid_for(
        is_tool=isinstance(lockfile, (ToolCustomLockfile, ToolDefaultLockfile)),
        expected_invalidation_digest=lockfile.lockfile_hex_digest,
        user_interpreter_constraints=interpreter_constraints,
        interpreter_universe=python_setup.interpreter_versions_universe,
        user_requirements=user_requirements,
        manylinux=resolve_config.manylinux,
        requirement_constraints=(
            resolve_config.constraints_file.constraints
            if resolve_config.constraints_file
            else set()
        ),
        only_binary=resolve_config.only_binary,
        no_binary=resolve_config.no_binary,
    )
    if validation:
        return

    error_msg_kwargs = dict(
        metadata=metadata,
        validation=validation,
        lockfile=lockfile,
        user_interpreter_constraints=interpreter_constraints,
        user_requirements=user_requirements,
        maybe_constraints_file_path=(
            resolve_config.constraints_file.path if resolve_config.constraints_file else None
        ),
    )
    is_tool = isinstance(lockfile, (ToolCustomLockfile, ToolDefaultLockfile))
    msg_iter = (
        _invalid_tool_lockfile_error(**error_msg_kwargs)  # type: ignore[arg-type]
        if is_tool
        else _invalid_user_lockfile_error(**error_msg_kwargs)  # type: ignore[arg-type]
    )
    msg = "".join(msg_iter).strip()
    if python_setup.invalid_lockfile_behavior == InvalidLockfileBehavior.error:
        raise InvalidLockfileError(msg)
    logger.warning("%s", msg)


def _common_failure_reasons(
    failure_reasons: set[InvalidPythonLockfileReason], maybe_constraints_file_path: str | None
) -> Iterator[str]:
    if InvalidPythonLockfileReason.CONSTRAINTS_FILE_MISMATCH in failure_reasons:
        assert maybe_constraints_file_path is not None
        yield softwrap(
            f"""
            - The constraints file at {maybe_constraints_file_path} has changed from when the
            lockfile was generated. (Constraints files are set via the option
            `[python].resolves_to_constraints_file`)
            """
        )
    if InvalidPythonLockfileReason.ONLY_BINARY_MISMATCH in failure_reasons:
        yield softwrap(
            """
            - The `only_binary` arguments have changed from when the lockfile was generated.
            (`only_binary` is set via the options `[python].resolves_to_only_binary` and deprecated
            `[python].only_binary`)
            """
        )
    if InvalidPythonLockfileReason.NO_BINARY_MISMATCH in failure_reasons:
        yield softwrap(
            """
            - The `no_binary` arguments have changed from when the lockfile was generated.
            (`no_binary` is set via the options `[python].resolves_to_no_binary` and deprecated
            `[python].no_binary`)
            """
        )
    if InvalidPythonLockfileReason.MANYLINUX_MISMATCH in failure_reasons:
        yield softwrap(
            """
            - The `manylinux` argument has changed from when the lockfile was generated.
            (manylinux is set via the option `[python].resolver_manylinux`)
            """
        )


def _invalid_tool_lockfile_error(
    metadata: PythonLockfileMetadata,
    validation: LockfileMetadataValidation,
    lockfile: ToolCustomLockfile | ToolDefaultLockfile,
    *,
    user_requirements: set[PipRequirement],
    user_interpreter_constraints: InterpreterConstraints,
    maybe_constraints_file_path: str | None,
) -> Iterator[str]:
    tool_name = lockfile.resolve_name

    yield "You are using "
    yield "the `<default>` lockfile provided by Pants " if isinstance(
        lockfile, ToolDefaultLockfile
    ) else f"the lockfile at {lockfile.file_path} "
    yield softwrap(
        f"""
        to install the tool `{tool_name}`, but it is not compatible with your
        configuration:
        """
    ) + "\n\n"

    if any(
        i
        in (
            InvalidPythonLockfileReason.INVALIDATION_DIGEST_MISMATCH,
            InvalidPythonLockfileReason.REQUIREMENTS_MISMATCH,
        )
        for i in validation.failure_reasons
    ):
        yield softwrap(
            f"""
            - You have set different requirements than those used to generate the lockfile.
            You can fix this by updating `[{tool_name}].version`
            """
        )
        if lockfile.uses_source_plugins:
            yield f", `[{tool_name}].source_plugins`,"
        yield f" and/or `[{tool_name}].extra_requirements`, or by using a new custom lockfile.\n"
        if isinstance(metadata, PythonLockfileMetadataV2):
            not_in_user_reqs = metadata.requirements - user_requirements
            not_in_lock = user_requirements - metadata.requirements
            if not_in_lock:
                yield softwrap(
                    f"""
                    In the input requirements, but not in the lockfile:
                    {sorted(str(r) for r in not_in_lock)}
                    """
                ) + "\n"
            if not_in_user_reqs:
                yield softwrap(
                    f"""
                    In the lockfile, but not in the input requirements:
                    {sorted(str(r) for r in not_in_user_reqs)}
                    """
                ) + "\n"
            yield "\n"

    if InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH in validation.failure_reasons:
        yield softwrap(
            f"""
            - You have set interpreter constraints (`{user_interpreter_constraints}`) that
            are not compatible with those used to generate the lockfile
            (`{metadata.valid_for_interpreter_constraints}`).
            """
        )
        yield softwrap(
            f"""
            You can fix this by not setting `[{tool_name}].interpreter_constraints`,
            or by using a new custom lockfile.
            """
        ) if not lockfile.uses_project_interpreter_constraints else softwrap(
            f"""
            `{tool_name}` determines its interpreter constraints based on your code's own
            constraints. To fix this error, you can either change your code's constraints
            (see {doc_url('python-interpreter-compatibility')}) or generate a new
            custom lockfile.
            """
        )
        yield "\n\n"

    yield from _common_failure_reasons(validation.failure_reasons, maybe_constraints_file_path)

    yield softwrap(
        f"""
        To regenerate your lockfile based on your current configuration, run
        `{bin_name()} generate-lockfiles --resolve={tool_name}`.
        """
    ) if isinstance(lockfile, ToolCustomLockfile) else softwrap(
        f"""
        To generate a custom lockfile based on your current configuration, set
        `[{tool_name}].lockfile` to where you want to create the lockfile, then run
        `{bin_name()} generate-lockfiles --resolve={tool_name}`.
        """
    )


def _invalid_user_lockfile_error(
    metadata: PythonLockfileMetadataV2,
    validation: LockfileMetadataValidation,
    lockfile: Lockfile | LockfileContent,
    *,
    user_requirements: set[PipRequirement],
    user_interpreter_constraints: InterpreterConstraints,
    maybe_constraints_file_path: str | None,
) -> Iterator[str]:
    yield "You are using the lockfile "
    yield f"at {lockfile.file_path} " if isinstance(
        lockfile, Lockfile
    ) else f"synthetically created at {lockfile.file_content.path} "
    yield softwrap(
        f"""
        to install the resolve `{lockfile.resolve_name}` (from `[python].resolves`). However,
        it is not compatible with the current targets because:
        """
    ) + "\n\n"

    if InvalidPythonLockfileReason.REQUIREMENTS_MISMATCH in validation.failure_reasons:
        # Note that for user lockfiles, we only care that user requirements are a subset of the
        # lock. So, unlike tools, we do not report on requirements in the lock but not in
        # user_requirements.
        #
        # Also note that by the time we have gotten to this error message, we should have already
        # validated that the transitive closure is using the same resolve, via
        # pex_from_targets.py. This implies that we don't need to worry about users depending on
        # python_requirement targets that aren't in that code's resolve.
        not_in_lock = sorted(str(r) for r in user_requirements - metadata.requirements)
        yield softwrap(
            f"""
            - The targets depend on requirements that are not in the lockfile: {not_in_lock}

            This most often happens when adding a new requirement to your project, or bumping
            requirement versions. You can fix this by regenerating the lockfile with
            `generate-lockfiles`.
            """
        ) + "\n\n"

    if InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH in validation.failure_reasons:
        yield softwrap(
            f"""
            - The targets use interpreter constraints (`{user_interpreter_constraints}`) that
            are not a subset of those used to generate the lockfile
            (`{metadata.valid_for_interpreter_constraints}`).

            The lockfile's interpreter constraints are set by the option
            `[python].resolves_to_interpreter_constraints`, which determines how the lockfile is
            generated. Note that that option only changes how the lockfile is generated; you must
            still set interpreter constraints for targets via `[python].interpreter_constraints` and
            the `interpreter_constraints` field ({doc_url('python-interpreter-compatibility')}).
            All targets must have interpreter constraints that are a subset of their resolve's
            constraints.

            To fix this, you can either adjust the interpreter constraints of the targets
            which use the resolve '{lockfile.resolve_name}', or adjust
            `[python].resolves_to_interpreter_constraints`
            then run `generate-lockfiles`.
            """
        ) + "\n\n"

    yield from _common_failure_reasons(validation.failure_reasons, maybe_constraints_file_path)

    yield "To regenerate your lockfile, "
    yield f"run `{bin_name()} generate-lockfiles --resolve={lockfile.resolve_name}`." if isinstance(
        lockfile, Lockfile
    ) else f"update your plugin generating this object: {lockfile}"


def rules():
    return collect_rules()
