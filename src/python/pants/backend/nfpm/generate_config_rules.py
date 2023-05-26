# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

import yaml

from pants.backend.nfpm.config import NfpmContent, file_info
from pants.backend.nfpm.field_sets import NfpmPackageFieldSet
from pants.backend.nfpm.fields.contents import (
    NfpmContentDirDstField,
    NfpmContentDstField,
    NfpmContentSrcField,
    NfpmContentSymlinkDstField,
    NfpmContentSymlinkSrcField,
    NfpmContentTypeField,
)
from pants.core.goals.package import TransitiveTargetsWithoutTraversingPackagesRequest
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import TransitiveTargets
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class RequestNfpmPackageConfig:
    field_set: NfpmPackageFieldSet


@dataclass(frozen=True)
class NfpmPackageConfig:
    digest: Digest  # digest contains nfpm.yaml


@rule(level=LogLevel.DEBUG)
async def generate_nfpm_yaml(request: RequestNfpmPackageConfig) -> NfpmPackageConfig:
    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsWithoutTraversingPackagesRequest([request.field_set.address]),
    )

    # Fist get the config that can be constructed from the target itself.
    nfpm_package_target = transitive_targets.roots[0]
    config = request.field_set.nfpm_config(nfpm_package_target)

    # Second, gather package contents from hydrated deps.
    contents: list[NfpmContent] = config["contents"]

    # NB: TransitiveTargets is AFTER target generation/expansion (so there are no target generators)
    for tgt in transitive_targets.dependencies:
        if tgt.has_field(NfpmContentDirDstField):  # an NfpmContentDir
            dst = tgt[NfpmContentDirDstField].value
            if dst is None:
                continue
            contents.append(
                NfpmContent(
                    type="dir",
                    dst=dst,
                    file_info=file_info(tgt),
                )
            )
        elif tgt.has_field(NfpmContentSymlinkDstField):  # an NfpmContentSymlink
            src = tgt[NfpmContentSymlinkSrcField].value
            dst = tgt[NfpmContentSymlinkDstField].value
            if src is None or dst is None:
                continue
            contents.append(
                NfpmContent(
                    type="symlink",
                    src=src,
                    dst=dst,
                    file_info=file_info(tgt),
                )
            )
        elif tgt.has_field(NfpmContentDstField):  # an NfpmContentFile
            src = tgt[NfpmContentSrcField].value
            dst = tgt[NfpmContentDstField].value
            # TODO: handle the 'source' field that can implicitly provide 'src'
            if src is None or dst is None:
                continue
            contents.append(
                NfpmContent(
                    type=tgt[NfpmContentTypeField].value or NfpmContentTypeField.default,
                    src=src,
                    dst=dst,
                    file_info=file_info(tgt),
                )
            )

    contents.sort(key=lambda d: d["dst"])

    nfpm_yaml = "# Generated by Pantsbuild\n"
    nfpm_yaml += yaml.safe_dump(config)
    nfpm_yaml_content = FileContent("nfpm.yaml", nfpm_yaml.encode())

    digest = await Get(Digest, CreateDigest([nfpm_yaml_content]))
    return NfpmPackageConfig(digest)


def rules():
    return [*collect_rules()]
