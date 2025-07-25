# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""tsconfig.json is primarily used by the typescript compiler in order to resolve types during
compilation. The format is also used by IDE:s to provide intellisense. The format is used for
projects that use only javascript, and is then named jsconfig.json.

See https://code.visualstudio.com/docs/languages/jsconfig
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePath

from pants.engine.collection import Collection
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.internals.selectors import Get, concurrently
from pants.engine.intrinsics import get_digest_contents, path_globs_to_digest
from pants.engine.rules import Rule, collect_rules, rule
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TSConfig:
    """Parsed tsconfig.json fields with `extends` substitution applied."""

    path: str
    module_resolution: str | None = None
    paths: FrozenDict[str, tuple[str, ...]] | None = None
    base_url: str | None = None
    out_dir: str | None = None

    @property
    def resolution_root_dir(self) -> str:
        directory = os.path.dirname(self.path)
        return os.path.join(directory, self.base_url) if self.base_url else directory
    
    def validate_outdir(self) -> None:
        # Check that outDir is explicitly set
        if not self.out_dir:
            raise ValueError(
                f"TypeScript configuration at '{self.path}' is missing required 'outDir' setting. "
                f"TypeScript type-checking requires an explicit outDir in compilerOptions to work properly. "
                f"Add '\"outDir\": \"./dist\"' (or your preferred output directory) to the compilerOptions "
                f"in {self.path}."
            )
        
        # Reject paths with .. components (prevents cross-package conflicts)
        if ".." in self.out_dir:
            raise ValueError(
                f"TypeScript configuration at '{self.path}' has outDir '{self.out_dir}' "
                f"that uses '..' path components. Each package should use its own output directory "
                f"within its package boundary (e.g., './dist', './build'). Cross-package output "
                f"directories can cause build conflicts where packages overwrite each other's artifacts."
            )
        
        # Reject absolute paths (prevents escaping project entirely)
        if os.path.isabs(self.out_dir):
            raise ValueError(
                f"TypeScript configuration at '{self.path}' has absolute outDir '{self.out_dir}'. "
                f"Use a relative path within the package directory instead (e.g., './dist', './build'). "
                f"Absolute paths break build hermeticity and can cause security issues."
            )


class AllTSConfigs(Collection[TSConfig]):
    pass


@dataclass(frozen=True)
class ParseTSConfigRequest:
    content: FileContent
    others: DigestContents


async def _read_parent_config(
    child_path: str,
    extends_path: str,
    others: DigestContents,
) -> TSConfig | None:
    if child_path.endswith(".json"):
        relative = os.path.dirname(child_path)
    else:
        relative = child_path
    relative = os.path.normpath(os.path.join(relative, extends_path))
    for target_file in ("tsconfig.json", "jsconfig.json"):
        if not extends_path.endswith(".json"):
            relative = os.path.join(relative, target_file)
        parent = next((other for other in others if other.path == relative), None)
        if parent:
            break
    if not parent:
        logger.warning(
            f"pants could not locate {child_path}'s 'extends' at {relative}. Found: {[other.path for other in others]}."
        )
        return None
    return await Get(  # Must be a Get until https://github.com/pantsbuild/pants/pull/21174 lands
        TSConfig, ParseTSConfigRequest(parent, others)
    )


def _clean_tsconfig_contents(content: str) -> str:
    """The tsconfig.json uses a format similar to JSON ("JSON with comments"), but there are some
    important differences:

    * tsconfig.json allows both single-line (`// comment`) and multi-line comments (`/* comment */`) to be added
    anywhere in the file.
    * Trailing commas in arrays and objects are permitted.

    TypeScript uses its own parser to read the file; in standard JSON, trailing commas or comments are not allowed.
    """
    # This pattern matches:
    # 1. Strings: "..." or '...'
    # 2. Single-line comments: //...
    # 3. Multi-line comments: /*...*/
    # 4. Everything else (including potential trailing commas)
    pattern = r'("(?:\\.|[^"\\])*")|(\'(?:\\.|[^\'\\])*\')|(//.*?$)|(/\*.*?\*/)|,(\s*[\]}])'

    def replace(match):
        if match.group(1) or match.group(2):  # It's a string
            return match.group(0)  # Return the string as is
        elif match.group(3) or match.group(4):  # It's a comment
            return ""  # Remove the comment
        elif match.group(5):  # It's a trailing comma
            return match.group(5)  # Remove the comma keeping the closing brace/bracket
        return match.group(0)

    cleaned_content = re.sub(pattern, replace, content, flags=re.DOTALL | re.MULTILINE)
    return cleaned_content


def _parse_config_from_content(content: FileContent) -> tuple[TSConfig, str | None]:
    cleaned_tsconfig_contents = _clean_tsconfig_contents(content.content.decode("utf-8"))
    parsed_ts_config_json = FrozenDict.deep_freeze(json.loads(cleaned_tsconfig_contents))

    compiler_options = parsed_ts_config_json.get("compilerOptions", FrozenDict())
    return TSConfig(
        content.path,
        module_resolution=compiler_options.get("moduleResolution"),
        paths=compiler_options.get("paths"),
        base_url=compiler_options.get("baseUrl"),
        out_dir=compiler_options.get("outDir"),
    ), parsed_ts_config_json.get("extends")


@rule
async def parse_extended_ts_config(request: ParseTSConfigRequest) -> TSConfig:
    ts_config, extends = _parse_config_from_content(request.content)
    if not extends:
        return ts_config

    extended_parent = await _read_parent_config(ts_config.path, extends, request.others)
    if not extended_parent:
        return ts_config
    return TSConfig(
        ts_config.path,
        module_resolution=ts_config.module_resolution or extended_parent.module_resolution,
        paths=ts_config.paths or extended_parent.paths,
        base_url=ts_config.base_url or extended_parent.base_url,
        # Do NOT inherit outDir - paths in extended configs are resolved relative to where they're defined,
        # not where they're used, making inherited outDir values incorrect for child projects
        out_dir=ts_config.out_dir,
    )


@dataclass(frozen=True)
class TSConfigsRequest:
    target_file: str


@rule
async def construct_effective_ts_configs() -> AllTSConfigs:
    all_files = await path_globs_to_digest(PathGlobs(["**/tsconfig*.json", "**/jsconfig*.json"]))
    digest_contents = await get_digest_contents(all_files)

    return AllTSConfigs(
        await concurrently(
            parse_extended_ts_config(ParseTSConfigRequest(digest_content, digest_contents))
            for digest_content in digest_contents
        )
    )


@dataclass(frozen=True)
class ClosestTSConfig:
    ts_config: TSConfig | None


@dataclass(frozen=True)
class ParentTSConfigRequest:
    file: str


@rule(desc="Finding parent tsconfig.json")
async def find_parent_ts_config(req: ParentTSConfigRequest) -> ClosestTSConfig:
    all_configs = await construct_effective_ts_configs()
    configs_by_longest_path = sorted(all_configs, key=lambda config: len(config.path), reverse=True)
    for config in configs_by_longest_path:
        if PurePath(req.file).is_relative_to(os.path.dirname(config.path)):
            return ClosestTSConfig(config)
    return ClosestTSConfig(None)




def rules() -> Iterable[Rule]:
    return collect_rules()
