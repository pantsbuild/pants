# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from operator import itemgetter
from typing import ClassVar

from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


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
    import_map: FrozenDict[str, str] | None = None


@rule
async def generate_import_config(request: ImportConfigRequest) -> ImportConfig:
    key_fn = itemgetter(0)
    packages = sorted(request.import_paths_to_pkg_a_files.items(), key=key_fn)
    import_map = sorted((request.import_map or {}).items(), key=key_fn)
    lines = [
        "# import config",
        *(f"packagefile {import_path}={pkg_a_path}" for import_path, pkg_a_path in packages),
        *(f"importmap {old}={new}" for old, new in import_map),
    ]
    content = "\n".join(lines).encode("utf-8")
    result = await Get(Digest, CreateDigest([FileContent(ImportConfig.CONFIG_PATH, content)]))
    return ImportConfig(result)


def rules():
    return collect_rules()
