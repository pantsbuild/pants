# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.go.go_sources import load_go_binary
from pants.backend.go.go_sources.load_go_binary import LoadedGoBinaryRequest, setup_go_binary
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.intrinsics import merge_digests
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParseVendorModulesMetadataRequest(EngineAwareParameter):
    digest: Digest
    path: str

    def debug_hint(self) -> str | None:
        return str(self.path)


@dataclass(frozen=True)
class VendoredModuleMetadata:
    """Metadata from vendor/modules.txt for one module."""

    module_import_path: str
    module_version: str
    package_import_paths: frozenset[str]
    explicit: bool
    go_version: str | None

    @classmethod
    def from_json_dict(cls, data):
        return cls(
            module_import_path=data["mod_version"]["path"],
            module_version=data["mod_version"]["version"],
            package_import_paths=frozenset(data.get("package_import_paths", [])),
            explicit=data["explicit"],
            go_version=data.get("go_version"),
        )


@dataclass(frozen=True)
class ParseVendorModulesMetadataResult:
    modules: tuple[VendoredModuleMetadata, ...]


@dataclass(frozen=True)
class VendorModulesParserSetup:
    digest: Digest
    path: str


@rule
async def setup_vendor_modules_txt_parser() -> VendorModulesParserSetup:
    output_name = "__go_parse_vendor__"
    binary = await setup_go_binary(
        LoadedGoBinaryRequest("parse_vendor_modules", ("parse.go", "semver.go"), output_name),
        **implicitly(),
    )
    return VendorModulesParserSetup(
        digest=binary.digest,
        path=f"./{output_name}",
    )


@rule
async def parse_vendor_modules_metadata(
    request: ParseVendorModulesMetadataRequest,
    parser: VendorModulesParserSetup,
) -> ParseVendorModulesMetadataResult:
    input_digest = await merge_digests(MergeDigests([request.digest, parser.digest]))
    result = await execute_process_or_raise(
        **implicitly(
            Process(
                argv=(parser.path, request.path),
                input_digest=input_digest,
                description=f"Parse vendor modules list: `{request.path}`",
                level=LogLevel.DEBUG,
            )
        ),
    )

    raw_modules = json.loads(result.stdout)
    modules = [VendoredModuleMetadata.from_json_dict(m) for m in raw_modules]

    return ParseVendorModulesMetadataResult(
        modules=tuple(modules),
    )


def rules() -> Iterable[Rule]:
    return (
        *collect_rules(),
        *load_go_binary.rules(),
    )
