# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from pants.backend.python.target_types import PythonRequirementsField
from pants.engine.fs import FileContent
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet

if TYPE_CHECKING:
    from pants.backend.python.util_rules.pex import Pex


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
