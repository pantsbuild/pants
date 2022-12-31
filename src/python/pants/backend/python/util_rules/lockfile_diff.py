# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any, Mapping

from packaging.version import LegacyVersion, Version, parse

from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
    LockfileContent,
)
from pants.core.goals.generate_lockfiles import (
    LockfileGenerateDiff,
    LockfileGenerateDiffResult,
    LockfileRequirements,
    RequirementName,
)
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule

logger = logging.getLogger(__name__)


class PythonLockfileGenerateDiff(LockfileGenerateDiff):
    pass


@dataclass(frozen=True, order=True)
class PythonRequirementVersion:
    _parsed: Version | LegacyVersion

    @classmethod
    def parse(cls, version: str) -> PythonRequirementVersion:
        return cls(parse(version))

    def __str__(self) -> str:
        return str(self._parsed)

    def __getattr__(self, key: str) -> Any:
        return getattr(self._parsed, key)


def _pex_lockfile_requirements(lockfile_data: Mapping[str, Any] | None) -> LockfileRequirements:
    if not lockfile_data:
        return LockfileRequirements({})

    # Setup generators
    locked_resolves = (
        (
            (RequirementName(r["project_name"]), PythonRequirementVersion.parse(r["version"]))
            for r in resolve["locked_requirements"]
        )
        for resolve in lockfile_data["locked_resolves"]
    )

    try:
        requirements = dict(itertools.chain.from_iterable(locked_resolves))
    except KeyError as e:
        from pprint import pformat

        logger.debug(f"Failed to parse PEX lockfile: {e}\n{pformat(lockfile_data)}")
        requirements = {}

    return LockfileRequirements(requirements)


@rule
async def generate_python_lockfile_diff(
    request: PythonLockfileGenerateDiff,
) -> LockfileGenerateDiffResult:
    lockfile = request.lockfile
    new_content = await Get(DigestContents, Digest, lockfile.digest)
    old, new = await MultiGet(
        Get(
            LoadedLockfile,
            LoadedLockfileRequest(
                Lockfile(
                    file_path=lockfile.path,
                    file_path_description_of_origin="generated lockfile",
                    resolve_name=lockfile.resolve_name,
                ),
                parse_lockfile=True,
            ),
        ),
        Get(
            LoadedLockfile,
            LoadedLockfileRequest(
                LockfileContent(
                    file_content=next(c for c in new_content if c.path == lockfile.path),
                    resolve_name=lockfile.resolve_name,
                ),
                parse_lockfile=True,
            ),
        ),
    )

    return LockfileGenerateDiffResult.create(
        path=lockfile.path,
        resolve_name=lockfile.resolve_name,
        old=_pex_lockfile_requirements(old.lockfile_data),
        new=_pex_lockfile_requirements(new.lockfile_data),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(LockfileGenerateDiff, PythonLockfileGenerateDiff),
    )
