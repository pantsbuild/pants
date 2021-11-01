# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from pants.backend.terraform.target_types import TerraformFieldSet
from pants.backend.terraform.tool import TerraformProcess
from pants.build_graph.address import Address
from pants.core.goals.style_request import StyleRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import pluralize


@frozen_after_init
@dataclass(unsafe_hash=True)
class StyleSetupRequest:
    request: StyleRequest[TerraformFieldSet]
    args: tuple[str, ...]

    def __init__(self, request: StyleRequest[TerraformFieldSet], args: Iterable[str]):
        self.request = request
        self.args = tuple(args)


@dataclass(frozen=True)
class StyleSetup:
    directory_to_process: dict[str, tuple[TerraformProcess, tuple[Address, ...]]]
    original_digest: Digest


@rule(level=LogLevel.DEBUG)
async def setup_terraform_style(setup_request: StyleSetupRequest) -> StyleSetup:
    source_files_by_field_set = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest([field_set.sources]),
        )
        for field_set in setup_request.request.field_sets
    )

    source_files_snapshot = (
        await Get(Snapshot, MergeDigests(sfs.snapshot.digest for sfs in source_files_by_field_set))
        if setup_request.request.prior_formatter_result is None
        else setup_request.request.prior_formatter_result
    )

    # `terraform` operates on a directory-by-directory basis. First determine the directories in
    # the snapshot. This does not use `source_files_snapshot.dirs` because that will be empty if the files
    # are in a single directory.
    directories = defaultdict(list)
    for source_files, field_set in zip(source_files_by_field_set, setup_request.request.field_sets):
        for file in source_files.snapshot.files:
            directory = os.path.dirname(file)
            if directory == "":
                directory = "."
            directories[directory].append((file, field_set.address))

    # Then create a process for each directory.
    directory_to_process = {}
    for directory, files_and_addresses_in_directory in directories.items():
        args = list(setup_request.args)
        args.append(directory)

        files_in_directory = tuple(f for f, _ in files_and_addresses_in_directory)
        addresses = tuple(a for _, a in files_and_addresses_in_directory)

        joined_args = " ".join(setup_request.args)
        process = TerraformProcess(
            args=tuple(args),
            input_digest=source_files_snapshot.digest,
            output_files=files_in_directory,
            description=f"Run `terraform {joined_args}` on {pluralize(len(files_in_directory), 'file')}.",
        )

        directory_to_process[directory] = (process, addresses)

    return StyleSetup(
        directory_to_process=directory_to_process, original_digest=source_files_snapshot.digest
    )


def rules():
    return [
        *collect_rules(),
    ]
