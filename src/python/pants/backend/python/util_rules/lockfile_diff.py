# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from packaging.version import parse

if TYPE_CHECKING:
    # We seem to get a version of `packaging` that doesn't have `LegacyVersion` when running
    # pytest..
    from packaging.version import LegacyVersion, Version

from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
    LockfileContent,
)
from pants.base.exceptions import EngineError
from pants.core.goals.generate_lockfiles import LockfileDiff, LockfilePackages, PackageName
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, rule_helper
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class PythonRequirementVersion:
    _parsed: LegacyVersion | Version

    @classmethod
    def parse(cls, version: str) -> PythonRequirementVersion:
        return cls(parse(version))

    def __str__(self) -> str:
        return str(self._parsed)

    def __getattr__(self, key: str) -> Any:
        return getattr(self._parsed, key)


def _pex_lockfile_requirements(
    lockfile_data: Mapping[str, Any] | None, path: str | None = None
) -> LockfilePackages:
    if not lockfile_data:
        return LockfilePackages({})

    try:
        # Setup generators
        locked_resolves = (
            (
                (PackageName(r["project_name"]), PythonRequirementVersion.parse(r["version"]))
                for r in resolve["locked_requirements"]
            )
            for resolve in lockfile_data["locked_resolves"]
        )
        requirements = dict(itertools.chain.from_iterable(locked_resolves))
    except KeyError as e:
        if path:
            logger.warning(f"{path}: Failed to parse lockfile: {e}")

        requirements = {}

    return LockfilePackages(requirements)


@rule_helper
async def _parse_lockfile(lockfile: Lockfile | LockfileContent) -> FrozenDict[str, Any] | None:
    try:
        loaded = await Get(
            LoadedLockfile,
            LoadedLockfileRequest(lockfile),
        )
        fc = await Get(DigestContents, Digest, loaded.lockfile_digest)
        parsed_lockfile = json.loads(fc[0].content)
        return FrozenDict.deep_freeze(parsed_lockfile)
    except EngineError:
        # May fail in case the file doesn't exist, which is expected when parsing the "old" lockfile
        # the first time a new lockfile is generated.
        return None
    except json.JSONDecodeError as e:
        file_path = (
            lockfile.file_path if isinstance(lockfile, Lockfile) else lockfile.file_content.path
        )
        logger.debug(f"{file_path}: Failed to parse lockfile contents: {e}")
        return None


@rule_helper
async def _generate_python_lockfile_diff(
    digest: Digest, resolve_name: str, path: str
) -> LockfileDiff:
    new_content = await Get(DigestContents, Digest, digest)
    new = await _parse_lockfile(
        LockfileContent(
            file_content=next(c for c in new_content if c.path == path),
            resolve_name=resolve_name,
        )
    )
    old = await _parse_lockfile(
        Lockfile(
            file_path=path,
            file_path_description_of_origin="generated lockfile",
            resolve_name=resolve_name,
        )
    )
    return LockfileDiff.create(
        path=path,
        resolve_name=resolve_name,
        old=_pex_lockfile_requirements(old),
        new=_pex_lockfile_requirements(new, path),
    )
