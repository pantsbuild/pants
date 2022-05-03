# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Iterator

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior, PythonSetup
from pants.backend.python.target_types import PythonRequirementsField, parse_requirements_file
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    InvalidPythonLockfileReason,
    PythonLockfileMetadata,
    PythonLockfileMetadataV2,
)
from pants.core.util_rules.lockfile_metadata import InvalidLockfileError, LockfileMetadataValidation
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    GlobMatchErrorBehavior,
    PathGlobs,
)
from pants.engine.rules import Get, collect_rules, rule
from pants.util.docutil import bin_name, doc_url
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet

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
    constraints_strings: FrozenOrderedSet[str] | None
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
                f"The lockfile {from_superset.original_lockfile} was not in PEX's "
                "native format, and so cannot be directly used as a superset."
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

    def __bool__(self) -> bool:
        return bool(self.req_strings)


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
) -> None:
    """Given interpreter constraints and requirements to be consumed, validate lockfile metadata."""

    # TODO(#12314): Improve the exception if invalid strings
    user_requirements = {PipRequirement.parse(i) for i in consumed_req_strings}
    validation = metadata.is_valid_for(
        is_tool=isinstance(lockfile, (ToolCustomLockfile, ToolDefaultLockfile)),
        expected_invalidation_digest=lockfile.lockfile_hex_digest,
        user_interpreter_constraints=interpreter_constraints,
        interpreter_universe=python_setup.interpreter_universe,
        user_requirements=user_requirements,
    )
    if validation:
        return

    error_msg_kwargs = dict(
        metadata=metadata,
        validation=validation,
        lockfile=lockfile,
        user_interpreter_constraints=interpreter_constraints,
        user_requirements=user_requirements,
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


def _invalid_tool_lockfile_error(
    metadata: PythonLockfileMetadata,
    validation: LockfileMetadataValidation,
    lockfile: ToolCustomLockfile | ToolDefaultLockfile,
    *,
    user_requirements: set[PipRequirement],
    user_interpreter_constraints: InterpreterConstraints,
) -> Iterator[str]:
    tool_name = lockfile.resolve_name

    yield "You are using "
    yield "the `<default>` lockfile provided by Pants " if isinstance(
        lockfile, ToolDefaultLockfile
    ) else f"the lockfile at {lockfile.file_path} "
    yield (
        f"to install the tool `{tool_name}`, but it is not compatible with your "
        "configuration: "
        "\n\n"
    )

    if any(
        i
        in (
            InvalidPythonLockfileReason.INVALIDATION_DIGEST_MISMATCH,
            InvalidPythonLockfileReason.REQUIREMENTS_MISMATCH,
        )
        for i in validation.failure_reasons
    ):
        yield (
            "- You have set different requirements than those used to generate the lockfile. "
            f"You can fix this by updating `[{tool_name}].version`"
        )
        if lockfile.uses_source_plugins:
            yield f", `[{tool_name}].source_plugins`,"
        yield f" and/or `[{tool_name}].extra_requirements`, or by using a new custom lockfile.\n"
        if isinstance(metadata, PythonLockfileMetadataV2):
            not_in_user_reqs = metadata.requirements - user_requirements
            not_in_lock = user_requirements - metadata.requirements
            if not_in_lock:
                yield (
                    "In the input requirements, but not in the lockfile: "
                    f"{sorted(str(r) for r in not_in_lock)}\n"
                )
            if not_in_user_reqs:
                yield (
                    "In the lockfile, but not in the input requirements: "
                    f"{sorted(str(r) for r in not_in_user_reqs)}\n"
                )
            yield "\n"

    if InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH in validation.failure_reasons:
        yield (
            f"- You have set interpreter constraints (`{user_interpreter_constraints}`) that "
            "are not compatible with those used to generate the lockfile "
            f"(`{metadata.valid_for_interpreter_constraints}`). "
        )
        yield (
            f"You can fix this by not setting `[{tool_name}].interpreter_constraints`, "
            "or by using a new custom lockfile. "
        ) if not lockfile.uses_project_interpreter_constraints else (
            f"`{tool_name}` determines its interpreter constraints based on your code's own "
            "constraints. To fix this error, you can either change your code's constraints "
            f"(see {doc_url('python-interpreter-compatibility')}) or generate a new "
            "custom lockfile. "
        )
        yield "\n\n"

    yield (
        "To regenerate your lockfile based on your current configuration, run "
        f"`{bin_name()} generate-lockfiles --resolve={tool_name}`. "
    ) if isinstance(lockfile, ToolCustomLockfile) else (
        "To generate a custom lockfile based on your current configuration, set "
        f"`[{tool_name}].lockfile` to where you want to create the lockfile, then run "
        f"`{bin_name()} generate-lockfiles --resolve={tool_name}`. "
    )


def _invalid_user_lockfile_error(
    metadata: PythonLockfileMetadataV2,
    validation: LockfileMetadataValidation,
    lockfile: Lockfile | LockfileContent,
    *,
    user_requirements: set[PipRequirement],
    user_interpreter_constraints: InterpreterConstraints,
) -> Iterator[str]:
    yield "You are using the lockfile "
    yield f"at {lockfile.file_path}" if isinstance(
        lockfile, Lockfile
    ) else f"synthetically created at {lockfile.file_content.path}"
    yield (
        f" to install the resolve `{lockfile.resolve_name}` (from `[python].resolves`). However, "
        "it is not compatible with the current targets because:\n\n"
    )

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
        yield (
            f"- The targets depend on requirements that are not in the lockfile: {not_in_lock}\n"
            f"This most often happens when adding a new requirement to your project, or bumping "
            f"requirement versions. You can fix this by regenerating the lockfile with "
            f"`generate-lockfiles`.\n\n"
        )

    if InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH in validation.failure_reasons:
        yield (
            f"- The targets use interpreter constraints (`{user_interpreter_constraints}`) that "
            "are not a subset of those used to generate the lockfile "
            f"(`{metadata.valid_for_interpreter_constraints}`).\nThe lockfile's interpreter "
            f"constraints are set by the option `[python].resolves_to_interpreter_constraints`, "
            f"which determines how the lockfile is generated. Note that that option only changes "
            f"how the lockfile is generated; you must still set interpreter constraints for "
            f"targets via `[python].interpreter_constraints` and the `interpreter_constraints` "
            f"field ({doc_url('python-interpreter-compatibility')}). All targets must have "
            f"interpreter constraints that are a subset of their resolve's constraints.\n"
            f"To fix this, you can either adjust the interpreter constraints of the targets "
            f"which use the resolve '{lockfile.resolve_name}', or adjust "
            f"`[python].resolves_to_interpreter_constraints` "
            f"then run `generate-lockfiles`.\n\n"
        )

    yield "To regenerate your lockfile, "
    yield f"run `{bin_name()} generate-lockfiles --resolve={lockfile.resolve_name}`." if isinstance(
        lockfile, Lockfile
    ) else f"update your plugin generating this object: {lockfile}"


def rules():
    return collect_rules()
