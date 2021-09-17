# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os

from pants.core.target_types import (
    FilesSources,
    GenRuleCommandField,
    GenRuleOutputsField,
    GenRuleSources,
    GenRuleToolsField,
)
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.process import (
    BashBinary,
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    Process,
    ProcessResult,
    SearchPath,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    Sources,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class GenerateFilesFromGenRuleRequest(GenerateSourcesRequest):
    input = GenRuleSources
    output = FilesSources


@rule(desc="Running gen_rule", level=LogLevel.DEBUG)
async def run_gen_rule(
    request: GenerateFilesFromGenRuleRequest, bash: BashBinary
) -> GeneratedSources:
    gen_rule = request.protocol_target
    working_directory = gen_rule.address.spec_path
    command = gen_rule[GenRuleCommandField].value
    tools = gen_rule[GenRuleToolsField].value
    outputs = gen_rule[GenRuleOutputsField].value
    source_globs = gen_rule[GenRuleSources].value or ()

    if not (command and tools and outputs):
        return GeneratedSources(EMPTY_SNAPSHOT)

    tool_requests = [
        BinaryPathRequest(
            binary_name=tool,
            search_path=SearchPath(("/usr/bin", "/bin", "/usr/local/bin")),
        )
        for tool in tools
    ]
    tool_paths = await MultiGet(
        Get(BinaryPaths, BinaryPathRequest, request) for request in tool_requests
    )

    tools_env: dict[str, str] = {}
    for binary, tool_request in zip(tool_paths, tool_requests):
        if binary.first_path:
            tools_env[tool_request.binary_name] = binary.first_path.path
        else:
            raise BinaryNotFoundError(
                tool_request, rationale=f"execute gen_rule {gen_rule.address}"
            )

    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest([gen_rule.address]),
    )

    own_sources, dep_sources = await MultiGet(
        Get(
            Digest,
            PathGlobs(
                [os.path.join(working_directory, glob) for glob in source_globs],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"{gen_rule.address}'s `{GenRuleSources.alias}` field",
            ),
        ),
        Get(
            SourceFiles,
            SourceFilesRequest(
                sources_fields=[tgt.get(Sources) for tgt in transitive_targets.dependencies],
                for_sources_types=(
                    Sources,
                    FilesSources,
                ),
                enable_codegen=True,
            ),
        ),
    )

    sources = await Get(Snapshot, MergeDigests([own_sources, dep_sources.snapshot.digest]))
    output_files = [f for f in outputs if not f.endswith("/")]
    output_directories = [d for d in outputs if d.endswith("/")]

    if working_directory in sources.dirs:
        input_digest = sources.digest
    else:
        work_dir = await Get(Digest, CreateDigest([Directory(working_directory)]))
        input_digest = await Get(Digest, MergeDigests([sources.digest, work_dir]))

    result = await Get(
        ProcessResult,
        Process(
            argv=(bash.path, "-c", command),
            description=f"Running gen_rule {gen_rule.address}",
            env=tools_env,
            input_digest=input_digest,
            output_directories=output_directories,
            output_files=output_files,
            working_directory=working_directory,
        ),
    )

    output = await Get(Snapshot, AddPrefix(result.output_digest, working_directory))
    return GeneratedSources(output)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateFilesFromGenRuleRequest),
    ]
