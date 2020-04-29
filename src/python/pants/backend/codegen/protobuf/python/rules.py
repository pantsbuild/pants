# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.backend.codegen.protobuf.subsystems.protoc import Protoc
from pants.backend.codegen.protobuf.target_types import ProtobufSources
from pants.backend.python.target_types import PythonSources
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, FileContent, InputFilesContent, Snapshot
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import goal_rule, named_rule, subsystem_rule
from pants.engine.selectors import Get
from pants.engine.target import GeneratedSources, GenerateSourcesRequest, Sources, Targets
from pants.engine.unions import UnionRule


class GeneratePythonFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSources
    output = PythonSources


def generate_args() -> Tuple[str, ...]:
    args = []
    return tuple(args)


@named_rule(desc="Generate Python from Protobuf")
async def generate_python_from_protobuf(
    request: GeneratePythonFromProtobufRequest, protoc: Protoc
) -> GeneratedSources:
    protocol_sources = request.protocol_sources
    downloaded_protoc_binary = await Get[DownloadedExternalTool](
        ExternalToolRequest, protoc.get_request(Platform.current)
    )
    # TODO: figure out how to create an empty directory with the engine.
    output_dir = await Get[Digest](InputFilesContent([FileContent("_generated_files/_dummy", b"")]))
    input_digest = await Get[Digest](
        DirectoriesToMerge(
            (protocol_sources.directory_digest, downloaded_protoc_binary.digest, output_dir)
        )
    )
    result = await Get[ProcessResult](
        Process(
            (
                downloaded_protoc_binary.exe,
                "--python_out",
                "_generated_files",
                *sorted(protocol_sources.files),
            ),
            input_files=input_digest,
            description=f"Generating Python sources from {request.protocol_target.address}.",
            output_directories=("_generated_files",),
        )
    )
    result_snapshot = await Get[Snapshot](Digest, result.output_directory_digest)
    return GeneratedSources(result_snapshot)


class ProtocOptions(GoalSubsystem):
    name = "run-protoc"


class ProtocGoal(Goal):
    subsystem_cls = ProtocOptions


@goal_rule
async def protoc_goal(targets: Targets, console: Console) -> ProtocGoal:
    all_sources = await Get[SourceFiles](
        AllSourceFilesRequest(
            (tgt.get(Sources) for tgt in targets),
            for_sources_types=(PythonSources,),
            enable_codegen=True,
        )
    )
    console.print_stdout(sorted(all_sources.snapshot.files))
    return ProtocGoal(0)


def rules():
    return [
        generate_python_from_protobuf,
        protoc_goal,
        UnionRule(GenerateSourcesRequest, GeneratePythonFromProtobufRequest),
        subsystem_rule(Protoc),
    ]
