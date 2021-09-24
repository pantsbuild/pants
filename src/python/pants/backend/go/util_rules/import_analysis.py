# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import ijson

from pants.backend.go.subsystems.golang import GoRoot
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

if TYPE_CHECKING:
    from pants.backend.go.util_rules.build_go_pkg import BuiltGoPackage


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


def parse_imports_for_golang_distribution(raw_json: bytes) -> dict[str, str]:
    import_paths: dict[str, str] = {}
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
    goroot: GoRoot,
) -> ResolvedImportPathsForGoLangDistribution:
    list_result = await Get(
        ProcessResult,
        GoSdkProcess(
            command=("list", "-json", "std"),
            description="Ask Go for its available import paths",
            absolutify_goroot=False,
        ),
    )
    import_paths = parse_imports_for_golang_distribution(list_result.stdout)
    import_descriptors: dict[str, ImportDescriptor] = {
        import_path: ImportDescriptor(digest=goroot.digest, path=path)
        for import_path, path in import_paths.items()
    }
    return ResolvedImportPathsForGoLangDistribution(
        import_path_mapping=FrozenDict(import_descriptors)
    )


@dataclass(frozen=True)
class GatherImportsRequest:
    packages: FrozenOrderedSet[BuiltGoPackage]
    include_stdlib: bool


@dataclass(frozen=True)
class GatheredImports:
    digest: Digest


@rule
async def generate_import_config(
    request: GatherImportsRequest, goroot_import_mappings: ResolvedImportPathsForGoLangDistribution
) -> GatheredImports:
    import_config_digests: dict[str, tuple[str, Digest]] = {}
    for pkg in request.packages:
        fp = pkg.object_digest.fingerprint
        prefixed_digest = await Get(Digest, AddPrefix(pkg.object_digest, f"__pkgs__/{fp}"))
        import_config_digests[pkg.import_path] = (fp, prefixed_digest)

    pkg_digests: OrderedSet[Digest] = OrderedSet()

    import_config = ["# import config"]
    for import_path, (fp, digest) in import_config_digests.items():
        pkg_digests.add(digest)
        import_config.append(f"packagefile {import_path}=__pkgs__/{fp}/__pkg__.a")

    if request.include_stdlib:
        for stdlib_pkg_importpath, stdlib_pkg in goroot_import_mappings.import_path_mapping.items():
            pkg_digests.add(stdlib_pkg.digest)
            import_config.append(
                f"packagefile {stdlib_pkg_importpath}={os.path.normpath(stdlib_pkg.path)}"
            )

    import_config_content = "\n".join(import_config).encode("utf-8")
    import_config_digest = await Get(
        Digest, CreateDigest([FileContent("./importcfg", import_config_content)])
    )
    pkg_digests.add(import_config_digest)

    digest = await Get(Digest, MergeDigests(pkg_digests))
    return GatheredImports(digest=digest)


def rules():
    return collect_rules()
