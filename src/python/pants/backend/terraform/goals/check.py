# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.terraform.dependency_inference import (
    GetTerraformDependenciesRequest,
    TerraformDependencies,
)
from pants.backend.terraform.partition import partition_files_by_directory
from pants.backend.terraform.target_types import TerraformFieldSet
from pants.backend.terraform.tool import TerraformProcess
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import pluralize


class TerraformValidateSubsystem(Subsystem):
    options_scope = "terraform-validate"
    name = "`terraform validate`"
    help = """Terraform validate options."""

    skip = SkipOption("check")


class TerraformCheckRequest(CheckRequest):
    field_set_type = TerraformFieldSet
    tool_name = TerraformValidateSubsystem.options_scope


@rule
async def terraform_check(
    request: TerraformCheckRequest, subsystem: TerraformValidateSubsystem
) -> CheckResults:
    if subsystem.skip:
        return CheckResults([], checker_name=request.tool_name)

    source_files = await Get(
        SourceFiles, SourceFilesRequest([field_set.sources for field_set in request.field_sets])
    )
    files_by_directory = partition_files_by_directory(source_files.files)

    fetched_deps = await Get(
        TerraformDependencies,
        GetTerraformDependenciesRequest(source_files, tuple(files_by_directory.keys())),
    )
    # just merge them all for now. This will probably be a problem with multiple TF sources requesting different versions of the same providers
    merged_fetched_deps = await Get(Digest, MergeDigests([x[1] for x in fetched_deps.fetched_deps]))

    sources_and_deps = await Get(
        Digest, MergeDigests([source_files.snapshot.digest, merged_fetched_deps])
    )

    results = await MultiGet(
        Get(
            FallibleProcessResult,
            TerraformProcess(
                args=("validate",),
                input_digest=sources_and_deps,
                output_files=tuple(files),
                description=f"Run `terraform fmt` on {pluralize(len(files), 'file')}.",
                chdir=directory,
            ),
        )
        for directory, files in files_by_directory.items()
    )

    check_results = []
    for directory, result in zip(files_by_directory, results):
        check_results.append(
            CheckResult.from_fallible_process_result(
                result, partition_description=f"`terraform validate` on `{directory}`"
            )
        )

    return CheckResults(check_results, checker_name=request.tool_name)


def rules():
    return (
        *collect_rules(),
        UnionRule(CheckRequest, TerraformCheckRequest),
    )
