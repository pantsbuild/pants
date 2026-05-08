# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import json
import logging
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from packaging.version import Version, parse

from pants.backend.python.util_rules.lockfile_metadata import LockfileFormat
from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfileRequest,
    Lockfile,
    load_lockfile,
    strip_comments_from_pex_json_lockfile,
)
from pants.base.exceptions import EngineError
from pants.core.goals.generate_lockfiles import LockfileDiff, LockfilePackages, PackageName
from pants.engine.fs import Digest
from pants.engine.intrinsics import get_digest_contents
from pants.engine.rules import implicitly
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class PythonRequirementVersion:
    _parsed: Version

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


def _uv_lockfile_requirements(
    lockfile_data: Mapping[str, Any] | None, path: str | None = None
) -> LockfilePackages:
    if not lockfile_data:
        return LockfilePackages({})

    requirements = {}
    for pkg in lockfile_data.get("package", []):
        try:
            name = pkg["name"]
            version = pkg.get("version")
            # Skip the synthetic virtual package, it's not interesting in diffs.
            if version is not None and not name.startswith("pants-lockfile-for-"):
                requirements[PackageName(name)] = PythonRequirementVersion.parse(version)
        except Exception as e:
            if path:
                logger.warning(f"{path}: Failed to parse package entry in lockfile: {e}")

    return LockfilePackages(requirements)


def _parse_lockfile_packages(
    content: bytes, lockfile_format: LockfileFormat, path: str | None = None
) -> LockfilePackages:
    """Parse the packages from lockfile content according to its format."""
    try:
        match lockfile_format:
            case LockfileFormat.PEX:
                # strip_comments_from_pex_json_lockfile is idempotent, so safe to call on
                # already-stripped content (e.g. when content was loaded via load_lockfile).
                stripped = strip_comments_from_pex_json_lockfile(content)
                data = FrozenDict.deep_freeze(json.loads(stripped))
                return _pex_lockfile_requirements(data, path)
            case LockfileFormat.UV:
                data = FrozenDict.deep_freeze(tomllib.loads(content.decode()))
                return _uv_lockfile_requirements(data, path)
            case LockfileFormat.CONSTRAINTS_DEPRECATED:
                # These can't meaningfully be diffed.
                return LockfilePackages({})
            case _:
                raise ValueError(f"Unrecognized lockfile format: {lockfile_format}")
    except Exception as e:
        if path:
            logger.debug(f"{path}: Failed to parse lockfile contents: {e}")
        return LockfilePackages({})


async def _generate_lockfile_diff(
    digest: Digest, resolve_name: str, path: str, new_format: LockfileFormat
) -> LockfileDiff:
    """Generate a diff between the newly generated lockfile and the existing one on disk.

    Handles all combinations of old vs. new and pex vs. uv lockfile formats.
    """
    new_digest_contents = await get_digest_contents(digest)
    new_content = next(c for c in new_digest_contents if c.path == path).content
    new_packages = _parse_lockfile_packages(new_content, new_format, path)

    old_packages = LockfilePackages({})
    try:
        loaded = await load_lockfile(
            LoadedLockfileRequest(
                Lockfile(
                    url=path,
                    url_description_of_origin="existing lockfile",
                    resolve_name=resolve_name,
                )
            ),
            **implicitly(),
        )
        old_content_entries = await get_digest_contents(loaded.lockfile_digest)
        old_content = next(iter(old_content_entries)).content
        old_packages = _parse_lockfile_packages(old_content, loaded.lockfile_format, path)
    except EngineError:
        # May fail if the file doesn't exist, which is expected the first time a new lockfile
        # is generated.
        pass

    return LockfileDiff.create(
        path=path,
        resolve_name=resolve_name,
        old=old_packages,
        new=new_packages,
    )
