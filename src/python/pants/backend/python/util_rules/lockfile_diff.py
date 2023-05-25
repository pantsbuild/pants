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
    strip_comments_from_pex_json_lockfile,
)
from pants.base.exceptions import EngineError
from pants.core.goals.generate_lockfiles import LockfileDiff, LockfilePackages, PackageName
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get
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


async def _parse_lockfile(lockfile: Lockfile) -> FrozenDict[str, Any] | None:
    try:
        loaded = await Get(
            LoadedLockfile,
            LoadedLockfileRequest(lockfile),
        )
        fc = await Get(DigestContents, Digest, loaded.lockfile_digest)
        parsed = await _parse_lockfile_content(next(iter(fc)).content, lockfile.url)
        return parsed
    except EngineError:
        # May fail in case the file doesn't exist, which is expected when parsing the "old" lockfile
        # the first time a new lockfile is generated.
        return None


async def _parse_lockfile_content(content: bytes, url: str) -> FrozenDict[str, Any] | None:
    try:
        parsed_lockfile = json.loads(content)
        return FrozenDict.deep_freeze(parsed_lockfile)
    except json.JSONDecodeError as e:
        logger.debug(f"{url}: Failed to parse lockfile contents: {e}")
        return None


async def _generate_python_lockfile_diff(
    digest: Digest, resolve_name: str, path: str
) -> LockfileDiff:
    new_digest_contents = await Get(DigestContents, Digest, digest)
    new_content = next(c for c in new_digest_contents if c.path == path).content
    new_content = strip_comments_from_pex_json_lockfile(new_content)
    new = await _parse_lockfile_content(new_content, path)
    old = await _parse_lockfile(
        Lockfile(
            url=path,
            url_description_of_origin="existing lockfile",
            resolve_name=resolve_name,
        )
    )
    return LockfileDiff.create(
        path=path,
        resolve_name=resolve_name,
        old=_pex_lockfile_requirements(old),
        new=_pex_lockfile_requirements(new, path),
    )
