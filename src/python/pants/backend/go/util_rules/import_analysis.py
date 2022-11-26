# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

import ijson

from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class GoStdLibImports(FrozenDict[str, str]):
    """A mapping of standard library import paths to the `.a` static file paths for that import
    path.

    For example, "net/smtp": "/absolute_path_to_goroot/pkg/darwin_arm64/net/smtp.a".
    """


@dataclass(frozen=True)
class GoStdLibImportsRequest:
    with_race_detector: bool


@rule(desc="Determine Go std lib's imports", level=LogLevel.DEBUG)
async def determine_go_std_lib_imports(request: GoStdLibImportsRequest) -> GoStdLibImports:
    maybe_race_arg = ["-race"] if request.with_race_detector else []
    list_result = await Get(
        ProcessResult,
        GoSdkProcess(
            # "-find" skips determining dependencies and imports for each package.
            command=("list", "-find", *maybe_race_arg, "-json", "std"),
            description="Ask Go for its available import paths",
        ),
    )
    result = {}
    for package_descriptor in ijson.items(list_result.stdout, "", multiple_values=True):
        import_path = package_descriptor.get("ImportPath")
        target = package_descriptor.get("Target")
        if not import_path or not target:
            continue
        result[import_path] = target
    return GoStdLibImports(result)


@dataclass(frozen=True)
class ImportConfig:
    """An `importcfg` file associating import paths to their `__pkg__.a` files."""

    digest: Digest

    CONFIG_PATH: ClassVar[str] = "./importcfg"


@dataclass(frozen=True)
class ImportConfigRequest:
    """Create an `importcfg` file associating import paths to their `__pkg__.a` files."""

    import_paths_to_pkg_a_files: FrozenDict[str, str]
    build_opts: GoBuildOptions
    include_stdlib: bool = True

    @classmethod
    def stdlib_only(cls, build_opts: GoBuildOptions) -> ImportConfigRequest:
        return cls(FrozenDict(), build_opts=build_opts, include_stdlib=True)


@rule
async def generate_import_config(request: ImportConfigRequest) -> ImportConfig:
    lines = [
        "# import config",
        *(
            f"packagefile {import_path}={pkg_a_path}"
            for import_path, pkg_a_path in request.import_paths_to_pkg_a_files.items()
        ),
    ]
    if request.include_stdlib:
        std_lib_imports = await Get(
            GoStdLibImports,
            GoStdLibImportsRequest(with_race_detector=request.build_opts.with_race_detector),
        )
        lines.extend(
            f"packagefile {import_path}={static_file_path}"
            for import_path, static_file_path in std_lib_imports.items()
        )
    content = "\n".join(lines).encode("utf-8")
    result = await Get(Digest, CreateDigest([FileContent(ImportConfig.CONFIG_PATH, content)]))
    return ImportConfig(result)


def rules():
    return collect_rules()
