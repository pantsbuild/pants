# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import pkg_resources

from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.nodejs import NodeJSToolProcess
from pants.backend.javascript.target_types import JSSourceField
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstalledJavascriptImportParser:
    digest: Digest


def _content_for_file(filename: str) -> FileContent:
    return FileContent(path=filename, content=pkg_resources.resource_string(__name__, filename))


@rule
async def install_javascript_parser() -> InstalledJavascriptImportParser:
    input_digest = await Get(
        Digest,
        CreateDigest(
            [
                _content_for_file("package.json"),
                _content_for_file("package-lock.json"),
                _content_for_file("script.cjs"),
            ]
        ),
    )
    result = await Get(
        ProcessResult,
        NodeJSToolProcess,
        NodeJSToolProcess.npm(
            args=("clean-install",),
            description="install @pants/javascript-source-import-parser modules.",
            input_digest=input_digest,
            output_directories=("node_modules",),
        ),
    )

    output_digest = await Get(Digest, MergeDigests((input_digest, result.output_digest)))

    return InstalledJavascriptImportParser(output_digest)


class JSImportStrings(FrozenOrderedSet[str]):
    pass


@dataclass(frozen=True)
class ParseJsImportStrings:
    source: JSSourceField


@rule
async def parse_js_imports(
    request: ParseJsImportStrings, parser: InstalledJavascriptImportParser
) -> JSImportStrings:
    files = await Get(
        SourceFiles, SourceFilesRequest([request.source], for_sources_types=[JSSourceField])
    )
    input_digest = await Get(Digest, MergeDigests([parser.digest, files.snapshot.digest]))

    result = await Get(
        FallibleProcessResult,
        NodeJSToolProcess,
        NodeJSToolProcess.npm(
            args=["run", "--silent", "parse", *files.files],
            description=f"Parsing imports for {files.files[0]}.",
            input_digest=input_digest,
        ),
    )
    if result.exit_code != 0:
        _logger.warning(
            softwrap(
                f"""
                Javascript source import parser failed for '{request.source.file_path}'.
                This is most likely due to an unrecoverable syntax error, such as redefining module imports.
                """
            )
        )
        _logger.warning(result.stderr.decode())
        return JSImportStrings()

    return JSImportStrings(result.stdout.decode().splitlines())


def rules() -> Iterable[UnionRule | Rule]:
    return [*nodejs.rules(), *source_files.rules(), *collect_rules()]
