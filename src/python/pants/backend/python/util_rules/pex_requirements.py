# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Iterator

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior, PythonSetup
from pants.backend.python.target_types import PythonRequirementsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    InvalidPythonLockfileReason,
    PythonLockfileMetadata,
    PythonLockfileMetadataV2,
)
from pants.core.util_rules.lockfile_metadata import InvalidLockfileError, LockfileMetadataValidation
from pants.engine.fs import FileContent
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
    req_strings: FrozenOrderedSet[str]
    lockfile_hex_digest: str | None = None


@dataclass(frozen=True)
class LockfileContent:
    file_content: FileContent
    resolve_name: str
    req_strings: FrozenOrderedSet[str]
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


@frozen_after_init
@dataclass(unsafe_hash=True)
class PexRequirements:
    req_strings: FrozenOrderedSet[str]
    constraints_strings: FrozenOrderedSet[str]
    # TODO: The constraints.txt resolve for `resolve_all_constraints` will be removed as part of
    # #12314, but in the meantime, it "acts like" a lockfile, but isn't actually typed as a Lockfile
    # because the constraints are modified in memory first. This flag marks a `PexRequirements`
    # resolve as being a request for the entire constraints file.
    is_all_constraints_resolve: bool
    repository_pex: Pex | None

    def __init__(
        self,
        req_strings: Iterable[str] = (),
        *,
        constraints_strings: Iterable[str] = (),
        is_all_constraints_resolve: bool = False,
        repository_pex: Pex | None = None,
    ) -> None:
        """
        :param req_strings: The requirement strings to resolve.
        :param constraints_strings: Constraints strings to apply during the resolve.
        :param repository_pex: An optional PEX to resolve requirements from via the Pex CLI
            `--pex-repository` option.
        """
        self.req_strings = FrozenOrderedSet(sorted(req_strings))
        self.constraints_strings = FrozenOrderedSet(sorted(constraints_strings))
        self.is_all_constraints_resolve = is_all_constraints_resolve
        self.repository_pex = repository_pex

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
    python_setup: PythonSetup,
) -> None:
    # TODO(#12314): Improve the exception if invalid strings
    user_requirements = {PipRequirement.parse(i) for i in lockfile.req_strings}
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
        "it is not compatible with the current targets:\n\n"
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
            f"- The targets use requirements that are not in the lockfile: {not_in_lock}\n"
            f"This most often happens when adding a new requirement to your project, or bumping "
            f"requirement versions. You can fix this by regenerating the lockfile with "
            f"`generate-lockfiles`.\n\n"
        )

    if InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH in validation.failure_reasons:
        yield (
            f"- The targets use interpreter constraints (`{user_interpreter_constraints}`) that "
            "are not compatible with those used to generate the lockfile "
            f"(`{metadata.valid_for_interpreter_constraints}`). You can fix this by either "
            f"adjusting your targets to use different interpreter constraints "
            f"({doc_url('python-interpreter-compatibility')}) or by generating the lockfile with "
            f"different interpreter constraints by setting the option "
            f"`[python].resolves_to_interpreter_constraints`, then running `generate-lockfiles`.\n\n"
        )

    yield "To regenerate your lockfile, "
    yield f"run `{bin_name()} generate-lockfiles --resolve={lockfile.resolve_name}`." if isinstance(
        lockfile, Lockfile
    ) else f"Update your plugin generating this object: {lockfile}"
