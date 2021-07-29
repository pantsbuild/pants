# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import logging
import textwrap
from dataclasses import dataclass
from typing import Dict

import ijson

from pants.backend.go.distribution import GoLangDistribution
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportDescriptor:
    digest: Digest
    path: str


# Note: There is only one subclass of this class currently. There will be additional subclasses once module
# support is added to the plugin.
@dataclass(frozen=True)
class ResolvedImportPaths:
    """Base class for types which map import paths provided by a source to how to access built
    package files for those import paths."""

    import_path_mapping: FrozenDict[str, ImportDescriptor]


@dataclass(frozen=True)
class ResolvedImportPathsForGoLangDistribution(ResolvedImportPaths):
    pass


def parse_imports_for_golang_distribution(raw_json: bytes) -> Dict[str, str]:
    import_paths: Dict[str, str] = {}
    package_descriptors = ijson.items(raw_json, "", multiple_values=True)
    for package_descriptor in package_descriptors:
        try:
            if "Target" in package_descriptor and "ImportPath" in package_descriptor:
                import_paths[package_descriptor["ImportPath"]] = package_descriptor["Target"]
        except Exception as ex:
            logger.error(
                f"error while parsing package descriptor: {ex}; package_descriptor: {json.dumps(package_descriptor)}"
            )
            raise
    return import_paths


@rule
async def analyze_imports_for_golang_distribution(
    goroot: GoLangDistribution,
    platform: Platform,
    bash: BashBinary,
) -> ResolvedImportPathsForGoLangDistribution:
    downloaded_goroot = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        goroot.get_request(platform),
    )

    # Note: The `go` tool requires GOPATH to be an absolute path which can only be resolved from within the
    # execution sandbox. Thus, this code uses a bash script to be able to resolve that path.
    analyze_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "analyze.sh",
                    textwrap.dedent(
                        """\
                export GOROOT="./go"
                export GOPATH="$(/bin/pwd)/gopath"
                export GOCACHE="$(/bin/pwd)/cache"
                mkdir -p "$GOPATH" "$GOCACHE"
                exec ./go/bin/go list -json std
                """
                    ).encode("utf-8"),
                )
            ]
        ),
    )

    input_root = await Get(Digest, MergeDigests([downloaded_goroot.digest, analyze_script_digest]))

    process = Process(
        argv=[bash.path, "./analyze.sh"],
        input_digest=input_root,
        description="Analyze import paths available in Go distribution.",
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)
    import_paths = parse_imports_for_golang_distribution(result.stdout)
    import_descriptors: Dict[str, ImportDescriptor] = {
        import_path: ImportDescriptor(digest=downloaded_goroot.digest, path=path)
        for import_path, path in import_paths.items()
    }
    return ResolvedImportPathsForGoLangDistribution(
        import_path_mapping=FrozenDict(import_descriptors)
    )


def rules():
    return [
        *collect_rules(),
    ]
