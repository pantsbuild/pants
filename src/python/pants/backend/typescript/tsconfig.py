# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable

from pants.engine.collection import Collection
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import directory_digest_to_digest_contents, path_globs_to_digest
from pants.engine.rules import Rule, collect_rules, rule
from pants.util.frozendict import FrozenDict

_CONFIG = "tsconfig.json"  # should be configurable


@dataclass(frozen=True)
class TSConfig:
    """Parsed tsconfig.json fields with `extends` substitution applied."""

    path: str
    module_resolution: str | None = None
    paths: FrozenDict[str, tuple[str, ...]] | None = None
    base_url: str | None = None
    extends: str | None = None

    @classmethod
    def parse_from_content(cls, content: FileContent) -> TSConfig:
        parsed_ts_config_json = FrozenDict.deep_freeze(json.loads(content.content))
        compiler_options = parsed_ts_config_json.get("compilerOptions", FrozenDict())
        return TSConfig(
            content.path,
            module_resolution=compiler_options.get("moduleResolution"),
            paths=compiler_options.get("path"),
            base_url=compiler_options.get("baseUrl"),
            extends=compiler_options.get("extends"),
        )


class AllTSConfigs(Collection[TSConfig]):
    pass


@dataclass(frozen=True)
class ParseTSConfigRequest:
    content: FileContent
    others: DigestContents


async def _read_parent_config(
    child_path: str, extends_path: str, others: DigestContents
) -> TSConfig:
    if child_path.endswith(_CONFIG):
        relative = os.path.dirname(child_path)
    else:
        relative = child_path
    relative = os.path.normpath(os.path.join(relative, extends_path))
    if not relative.endswith(_CONFIG):
        relative = os.path.join(relative, _CONFIG)
    parent = next((other for other in others if other.path == relative), None)
    if not parent:
        raise ValueError(
            f"pants could not locate {child_path}'s parent at {relative}. Found: {[other.path for other in others]}."
        )
    return await parse_extended_ts_config(ParseTSConfigRequest(parent, others))


@rule
async def parse_extended_ts_config(request: ParseTSConfigRequest) -> TSConfig:
    ts_config = TSConfig.parse_from_content(request.content)
    if ts_config.extends:
        extended_parent = await _read_parent_config(
            ts_config.path, ts_config.extends, request.others
        )
    else:
        extended_parent = TSConfig(ts_config.path)
    return TSConfig(
        ts_config.path,
        module_resolution=ts_config.module_resolution or extended_parent.module_resolution,
        paths=ts_config.paths or extended_parent.paths,
        base_url=ts_config.base_url or extended_parent.base_url,
        extends=ts_config.extends or extended_parent.extends,
    )


@rule
async def construct_effective_ts_configs() -> AllTSConfigs:
    all_files = await path_globs_to_digest(PathGlobs([f"**/{_CONFIG}"]))  # should be configurable
    digest_contents = await directory_digest_to_digest_contents(all_files)

    return AllTSConfigs(
        await concurrently(
            parse_extended_ts_config(ParseTSConfigRequest(digest_content, digest_contents))
            for digest_content in digest_contents
        )
    )


def rules() -> Iterable[Rule]:
    return collect_rules()
