# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Literal

from pants.engine.collection import Collection
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.internals.selectors import Get, concurrently
from pants.engine.intrinsics import directory_digest_to_digest_contents, path_globs_to_digest
from pants.engine.rules import Rule, collect_rules, rule
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class TSConfig:
    """Parsed tsconfig.json fields with `extends` substitution applied."""

    path: str
    module_resolution: str | None = None
    paths: FrozenDict[str, tuple[str, ...]] | None = None
    base_url: str | None = None

    @property
    def resolution_root_dir(self) -> str:
        directory = os.path.dirname(self.path)
        return os.path.join(directory, self.base_url) if self.base_url else directory


class AllTSConfigs(Collection[TSConfig]):
    pass


@dataclass(frozen=True)
class ParseTSConfigRequest:
    content: FileContent
    others: DigestContents
    target_file: Literal["tsconfig.json", "jsconfig.json"]


async def _read_parent_config(
    child_path: str,
    extends_path: str,
    others: DigestContents,
    target_file: Literal["tsconfig.json", "jsconfig.json"],
) -> TSConfig:
    if child_path.endswith(".json"):
        relative = os.path.dirname(child_path)
    else:
        relative = child_path
    relative = os.path.normpath(os.path.join(relative, extends_path))
    if not extends_path.endswith(".json"):
        relative = os.path.join(relative, target_file)
    parent = next((other for other in others if other.path == relative), None)
    if not parent:
        raise ValueError(
            f"pants could not locate {child_path}'s parent at {relative}. Found: {[other.path for other in others]}."
        )
    return await Get(  # Must be a Get until https://github.com/pantsbuild/pants/pull/21174 lands
        TSConfig, ParseTSConfigRequest(parent, others, target_file)
    )


def _parse_config_from_content(content: FileContent) -> tuple[TSConfig, str | None]:
    parsed_ts_config_json = FrozenDict.deep_freeze(json.loads(content.content))
    compiler_options = parsed_ts_config_json.get("compilerOptions", FrozenDict())
    return TSConfig(
        content.path,
        module_resolution=compiler_options.get("moduleResolution"),
        paths=compiler_options.get("paths"),
        base_url=compiler_options.get("baseUrl"),
    ), compiler_options.get("extends")


@rule
async def parse_extended_ts_config(request: ParseTSConfigRequest) -> TSConfig:
    ts_config, extends = _parse_config_from_content(request.content)
    if not extends:
        return ts_config

    extended_parent = await _read_parent_config(
        ts_config.path, extends, request.others, request.target_file
    )
    return TSConfig(
        ts_config.path,
        module_resolution=ts_config.module_resolution or extended_parent.module_resolution,
        paths=ts_config.paths or extended_parent.paths,
        base_url=ts_config.base_url or extended_parent.base_url,
    )


@dataclass(frozen=True)
class TSConfigsRequest:
    target_file: Literal["tsconfig.json", "jsconfig.json"]


@rule
async def construct_effective_ts_configs(req: TSConfigsRequest) -> AllTSConfigs:
    all_files = await path_globs_to_digest(PathGlobs([f"**/{req.target_file}"]))
    digest_contents = await directory_digest_to_digest_contents(all_files)

    return AllTSConfigs(
        await concurrently(
            parse_extended_ts_config(
                ParseTSConfigRequest(digest_content, digest_contents, req.target_file)
            )
            for digest_content in digest_contents
        )
    )


@dataclass(frozen=True)
class ClosestTSConfig:
    ts_config: TSConfig | None


@dataclass(frozen=True)
class ParentTSConfigRequest:
    file: str
    target_file: Literal["tsconfig.json", "jsconfig.json"]


@rule(desc="Finding parent tsconfig.json")
async def find_parent_ts_config(req: ParentTSConfigRequest) -> ClosestTSConfig:
    all_configs = await construct_effective_ts_configs(TSConfigsRequest(req.target_file))
    configs_by_longest_path = sorted(all_configs, key=lambda config: config.path, reverse=True)
    for config in configs_by_longest_path:
        if PurePath(req.file).is_relative_to(os.path.dirname(config.path)):
            return ClosestTSConfig(config)
    return ClosestTSConfig(None)


def rules() -> Iterable[Rule]:
    return collect_rules()
