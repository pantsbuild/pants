# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, Iterator

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior, PythonSetup
from pants.backend.python.target_types import PythonRequirementsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    InvalidPythonLockfileReason,
    PythonLockfileMetadata,
)
from pants.core.util_rules.lockfile_metadata import InvalidLockfileError, LockfileMetadataValidation
from pants.engine.fs import FileContent
from pants.util.docutil import doc_url
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet

if TYPE_CHECKING:
    from pants.backend.python.util_rules.pex import Pex


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lockfile:
    file_path: str
    file_path_description_of_origin: str
    lockfile_hex_digest: str | None
    req_strings: FrozenOrderedSet[str] | None


@dataclass(frozen=True)
class LockfileContent:
    file_content: FileContent
    lockfile_hex_digest: str | None
    req_strings: FrozenOrderedSet[str] | None


@dataclass(frozen=True)
class _ToolLockfileMixin:
    options_scope_name: str
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
        *,
        additional_requirements: Iterable[str] = (),
    ) -> PexRequirements:
        field_requirements = {str(python_req) for field in fields for python_req in field.value}
        return PexRequirements(
            {*field_requirements, *additional_requirements},
            constraints_strings=constraints_strings,
        )

    def __bool__(self) -> bool:
        return bool(self.req_strings)


def maybe_validate_metadata(
    parse_metadata: Callable[[], PythonLockfileMetadata],
    interpreter_constraints: InterpreterConstraints,
    requirements: (Lockfile | LockfileContent),
    python_setup: PythonSetup,
) -> None:
    if python_setup.invalid_lockfile_behavior == InvalidLockfileBehavior.ignore:
        return

    # TODO(#12314): Improve this message: `Requirement.parse` raises `InvalidRequirement`, which
    # doesn't have mypy stubs at the moment; it may be hard to catch this exception and typecheck.
    req_strings = (
        {PipRequirement.parse(i) for i in requirements.req_strings}
        if requirements.req_strings is not None
        else None
    )

    metadata = parse_metadata()
    validation = metadata.is_valid_for(
        requirements.lockfile_hex_digest,
        interpreter_constraints,
        python_setup.interpreter_universe,
        req_strings,
    )
    if validation:
        return

    message = (
        "".join(
            _invalid_tool_lockfile_error(
                validation,
                requirements,
                actual_interpreter_constraints=interpreter_constraints,
                lockfile_interpreter_constraints=metadata.valid_for_interpreter_constraints,
            )
        ).strip()
        if isinstance(requirements, (ToolCustomLockfile, ToolDefaultLockfile))
        else str(validation.failure_reasons)
    )

    if python_setup.invalid_lockfile_behavior == InvalidLockfileBehavior.error:
        raise InvalidLockfileError(message)
    logger.warning("%s", message)


def _invalid_tool_lockfile_error(
    validation: LockfileMetadataValidation,
    requirements: ToolCustomLockfile | ToolDefaultLockfile,
    *,
    actual_interpreter_constraints: InterpreterConstraints,
    lockfile_interpreter_constraints: InterpreterConstraints,
) -> Iterator[str]:
    tool_name = requirements.options_scope_name
    uses_source_plugins = requirements.uses_source_plugins
    uses_project_interpreter_constraints = requirements.uses_project_interpreter_constraints

    yield "You are using "
    yield "the `<default>` lockfile provided by Pants " if isinstance(
        requirements, ToolDefaultLockfile
    ) else f"the lockfile at {requirements.file_path} "
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
        # TODO(12314): Add message showing _which_ requirements diverged.
        yield (
            "- You have set different requirements than those used to generate the lockfile. "
            f"You can fix this by not setting `[{tool_name}].version`, "
        )
        if uses_source_plugins:
            yield f"`[{tool_name}].source_plugins`, "
        yield f"and `[{tool_name}].extra_requirements`, or by using a new custom lockfile.\n"

    if InvalidPythonLockfileReason.INTERPRETER_CONSTRAINTS_MISMATCH in validation.failure_reasons:
        yield (
            f"- You have set interpreter constraints (`{actual_interpreter_constraints}`) that "
            "are not compatible with those used to generate the lockfile "
            f"(`{lockfile_interpreter_constraints}`). "
        )
        yield (
            f"You can fix this by not setting `[{tool_name}].interpreter_constraints`, "
            "or by using a new custom lockfile. "
        ) if not uses_project_interpreter_constraints else (
            f"`{tool_name}` determines its interpreter constraints based on your code's own "
            "constraints. To fix this error, you can either change your code's constraints "
            f"(see {doc_url('python-interpreter-compatibility')}) or generat a new "
            "custom lockfile. "
        )
        yield "\n"

    yield "\n"
    yield (
        "To regenerate your lockfile based on your current configuration, run "
        f"`./pants generate-lockfiles --resolve={tool_name}`. "
    ) if isinstance(requirements, ToolCustomLockfile) else (
        "To generate a custom lockfile based on your current configuration, set "
        f"`[{tool_name}].lockfile` to where you want to create the lockfile, then run "
        f"`./pants generate-lockfiles --resolve={tool_name}`. "
    )
