# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

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
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

if TYPE_CHECKING:
    from pants.backend.go.util_rules.build_go_pkg import BuiltGoPackage


logger = logging.getLogger(__name__)


class GoStdLibImports(FrozenDict[str, str]):
    """A mapping of standard library import paths to the `.a` static file paths for that import
    path.

    For example, "net/smtp": "/absolute_path_to_goroot/pkg/darwin_arm64/net/smtp.a".
    """


@rule(desc="Determine Go std lib's imports", level=LogLevel.DEBUG)
async def determine_go_std_lib_imports() -> GoStdLibImports:
    list_result = await Get(
        ProcessResult,
        GoSdkProcess(
            command=("list", "-json", "std"),
            description="Ask Go for its available import paths",
            absolutify_goroot=False,
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
class GatherImportsRequest:
    packages: FrozenOrderedSet[BuiltGoPackage]
    include_stdlib: bool


@dataclass(frozen=True)
class GatheredImports:
    digest: Digest


@rule
async def generate_import_config(
    request: GatherImportsRequest, stdlib_imports: GoStdLibImports, goroot: GoRoot
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
        pkg_digests.add(goroot.digest)
        import_config.extend(
            f"packagefile {import_path}={os.path.normpath(static_file_path)}"
            for import_path, static_file_path in stdlib_imports.items()
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
