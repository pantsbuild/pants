# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.terraform.dependency_inference import (
    GetTerraformDependenciesRequest,
    TerraformDependencies,
)
from pants.backend.terraform.partition import partition_files_by_directory
from pants.backend.terraform.target_types import TerraformBackendConfigField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import SourcesField


@dataclass(frozen=True)
class TerraformInitRequest:
    sources: Iterable[SourcesField]
    backend_config: TerraformBackendConfigField

    # Not initialising the backend means we won't access remote state. Useful for `validate`
    initialise_backend: bool = False


@dataclass(frozen=True)
class InitialisedTerraform:
    sources_and_deps: Digest
    terraform_files: tuple[str, ...]
    chdir: str


@rule
async def init_terraform(request: TerraformInitRequest) -> InitialisedTerraform:
    source_files, backend_config = await MultiGet(
        Get(SourceFiles, SourceFilesRequest(request.sources)),
        Get(SourceFiles, SourceFilesRequest([request.backend_config])),
    )
    files_by_directory = partition_files_by_directory(source_files.files)

    fetched_deps = await Get(
        TerraformDependencies,
        GetTerraformDependenciesRequest(
            source_files,
            tuple(files_by_directory.keys()),
            backend_config,
            initialise_backend=request.initialise_backend,
        ),
    )

    merged_fetched_deps = await Get(Digest, MergeDigests([x[1] for x in fetched_deps.fetched_deps]))

    sources_and_deps = await Get(
        Digest, MergeDigests([source_files.snapshot.digest, merged_fetched_deps])
    )

    assert len(files_by_directory) == 1, "Multiple directories found, unable to identify a root"
    chdir, files = next(iter(files_by_directory.items()))
    return InitialisedTerraform(sources_and_deps, tuple(files), chdir)


def rules():
    return collect_rules()
