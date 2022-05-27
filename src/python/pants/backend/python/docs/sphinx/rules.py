# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.docs.sphinx.sphinx_subsystem import SphinxSubsystem
from pants.backend.python.docs.sphinx.target_types import SphinxProjectSourcesField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.engine.internals.native_engine import AddPrefix, Digest, RemovePrefix
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class SphinxPackageFieldSet(PackageFieldSet):
    required_fields = (SphinxProjectSourcesField,)

    sources: SphinxProjectSourcesField
    output_path: OutputPathField


_SPHINX_DEST_DIR = "__build"


@rule
async def generate_sphinx_docs(
    field_set: SphinxPackageFieldSet, sphinx: SphinxSubsystem
) -> BuiltPackage:
    sources, sphinx_pex = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(field_set.sources)),
        Get(VenvPex, PexRequest, sphinx.to_pex_request()),
    )
    result = await Get(
        ProcessResult,
        VenvPexProcess(
            sphinx_pex,
            argv=(
                # If the project is in the build root, set to ".".
                field_set.address.spec_path or ".",
                _SPHINX_DEST_DIR,
            ),
            output_directories=(_SPHINX_DEST_DIR,),
            input_digest=sources.snapshot.digest,
            description=f"Generate docs with Sphinx for {field_set.address}",
            level=LogLevel.INFO,
        ),
    )
    stripped_digest = await Get(Digest, RemovePrefix(result.output_digest, _SPHINX_DEST_DIR))
    dest_dir = field_set.output_path.value_or_default(file_ending=None)
    result_digest = await Get(Digest, AddPrefix(stripped_digest, dest_dir))
    return BuiltPackage(result_digest, artifacts=(BuiltPackageArtifact(dest_dir),))


def rules():
    return (
        *collect_rules(),
        *pex.rules(),
        UnionRule(PackageFieldSet, SphinxPackageFieldSet),
    )
