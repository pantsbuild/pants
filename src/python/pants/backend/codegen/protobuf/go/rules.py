# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.codegen.protobuf.go.subsystem import GoProtobufSubsystem
from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.target_types import ProtobufGrpcToggleField, ProtobufSourceField
from pants.backend.go.target_types import GoPackageSourcesField
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


class GenerateGoFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSourceField
    output = GoPackageSourcesField


@dataclass(frozen=True)
class SetupGoProtocPlugin:
    digest: Digest


@rule(desc="Generate Go from Protobuf", level=LogLevel.DEBUG)
async def generate_go_from_protobuf(
    request: GenerateGoFromProtobufRequest,
    protoc: Protoc,
    go_protoc_plugin: SetupGoProtocPlugin,
    go_protobuf: GoProtobufSubsystem,
) -> GeneratedSources:
    output_dir = "_generated_files"
    protoc_relpath = "__protoc"
    protoc_go_plugin_relpath = "__protoc_gen_go"

    downloaded_protoc_binary, empty_output_dir, transitive_targets = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, protoc.get_request(Platform.current)),
        Get(Digest, CreateDigest([Directory(output_dir)])),
        Get(TransitiveTargets, TransitiveTargetsRequest([request.protocol_target.address])),
    )

    # NB: By stripping the source roots, we avoid having to set the value `--proto_path`
    # for Protobuf imports to be discoverable.
    all_sources_stripped, target_sources_stripped = await MultiGet(
        Get(
            StrippedSourceFiles,
            SourceFilesRequest(
                tgt[ProtobufSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ProtobufSourceField)
            ),
        ),
        Get(
            StrippedSourceFiles, SourceFilesRequest([request.protocol_target[ProtobufSourceField]])
        ),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                all_sources_stripped.snapshot.digest,
                empty_output_dir,
            ]
        ),
    )

    maybe_grpc_plugin_args = []
    if request.protocol_target.get(ProtobufGrpcToggleField).value:
        maybe_grpc_plugin_args = [
            f"--go-grpc_out={output_dir}",
            "--go-grpc_opt=paths=source_relative",
        ]

    result = await Get(
        ProcessResult,
        Process(
            argv=[
                os.path.join(protoc_relpath, downloaded_protoc_binary.exe),
                f"--plugin=go={os.path.join('.', protoc_go_plugin_relpath, 'protoc-gen-go')}",
                f"--plugin=go-grpc={os.path.join('.', protoc_go_plugin_relpath, 'protoc-gen-go-grpc')}",
                f"--go_out={output_dir}",
                "--go_opt=paths=source_relative",
                *maybe_grpc_plugin_args,
                *target_sources_stripped.snapshot.files,
            ],
            # Note: Necessary or else --plugin option needs absolute path.
            env={"PATH": protoc_go_plugin_relpath},
            input_digest=input_digest,
            immutable_input_digests={
                protoc_relpath: downloaded_protoc_binary.digest,
                protoc_go_plugin_relpath: go_protoc_plugin.digest,
            },
            description=f"Generating Go sources from {request.protocol_target.address}.",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
        ),
    )

    normalized_digest, source_root = await MultiGet(
        Get(Digest, RemovePrefix(result.output_digest, output_dir)),
        Get(SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(normalized_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, normalized_digest)
    )
    return GeneratedSources(source_root_restored)


# Note: The versions of the Go protoc and gRPC plugins are hard coded in the following go.mod. To update,
# copy the following go.mod and go.sum contents to go.mod and go.sum files in a new directory. Then update the
# versions and run `go mod download all`. Copy the go.mod and go.sum contents back into these constants,
# making sure to repalce tabs with `\t`.

GO_PROTOBUF_GO_MOD = """\
module org.pantsbuild.backend.go.protobuf

go 1.17

require (
\tgoogle.golang.org/grpc/cmd/protoc-gen-go-grpc v1.2.0
\tgoogle.golang.org/protobuf v1.27.1
)

require (
\tgithub.com/golang/protobuf v1.5.0 // indirect
\tgithub.com/google/go-cmp v0.5.5 // indirect
\tgolang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 // indirect
)
"""

GO_PROTOBUF_GO_SUM = """\
github.com/golang/protobuf v1.5.0 h1:LUVKkCeviFUMKqHa4tXIIij/lbhnMbP7Fn5wKdKkRh4=
github.com/golang/protobuf v1.5.0/go.mod h1:FsONVRAS9T7sI+LIUmWTfcYkHO4aIWwzhcaSAoJOfIk=
github.com/google/go-cmp v0.5.5 h1:Khx7svrCpmxxtHBq5j2mp/xVjsi8hQMfNLvJFAlrGgU=
github.com/google/go-cmp v0.5.5/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
google.golang.org/grpc v1.2.0 h1:v8eFdETH8nqZHQ9x+0f2PLuU6W7zo5PFZuVEwH5126Y=
google.golang.org/grpc v1.2.0/go.mod h1:yo6s7OP7yaDglbqo1J04qKzAhqBH6lvTonzMVmEdcZw=
google.golang.org/grpc/cmd/protoc-gen-go-grpc v1.2.0 h1:TLkBREm4nIsEcexnCjgQd5GQWaHcqMzwQV0TX9pq8S0=
google.golang.org/grpc/cmd/protoc-gen-go-grpc v1.2.0/go.mod h1:DNq5QpG7LJqD2AamLZ7zvKE0DEpVl2BSEVjFycAAjRY=
google.golang.org/protobuf v1.27.1 h1:SnqbnDw1V7RiZcXPx5MEeqPv2s79L9i7BJUlG/+RurQ=
google.golang.org/protobuf v1.27.1/go.mod h1:9q0QmTI4eRPtz6boOQmLYwt+qCgq0jsYwAQnmE0givc=
"""


@rule
async def setup_go_protoc_plugin() -> SetupGoProtocPlugin:
    go_mod_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent("go.mod", GO_PROTOBUF_GO_MOD.encode()),
                FileContent("go.sum", GO_PROTOBUF_GO_SUM.encode()),
            ]
        ),
    )

    download_sources_result = await Get(
        ProcessResult,
        GoSdkProcess(
            ["mod", "download", "all"],
            input_digest=go_mod_digest,
            output_directories=("gopath",),
            description="Download Go `protoc` plugin sources.",
            allow_downloads=True,
        ),
    )

    go_plugin_build_result, go_grpc_plugin_build_result = await MultiGet(
        Get(
            ProcessResult,
            GoSdkProcess(
                ["install", "google.golang.org/protobuf/cmd/protoc-gen-go@v1.27.1"],
                input_digest=download_sources_result.output_digest,
                output_files=["gopath/bin/protoc-gen-go"],
                description="Build Go protobuf plugin for `protoc`.",
            ),
        ),
        Get(
            ProcessResult,
            GoSdkProcess(
                [
                    "install",
                    "google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.2.0",
                ],
                input_digest=download_sources_result.output_digest,
                output_files=["gopath/bin/protoc-gen-go-grpc"],
                description="Build Go gRPC protobuf plugin for `protoc`.",
            ),
        ),
    )
    if go_plugin_build_result.output_digest == EMPTY_DIGEST:
        raise AssertionError(
            f"Failed to build protoc-gen-go:\n"
            f"stdout:\n{go_plugin_build_result.stdout.decode()}\n\n"
            f"stderr:\n{go_plugin_build_result.stderr.decode()}"
        )
    if go_grpc_plugin_build_result.output_digest == EMPTY_DIGEST:
        raise AssertionError(
            f"Failed to build protoc-gen-go-grpc:\n"
            f"stdout:\n{go_grpc_plugin_build_result.stdout.decode()}\n\n"
            f"stderr:\n{go_grpc_plugin_build_result.stderr.decode()}"
        )

    merged_output_digests = await Get(
        Digest,
        MergeDigests(
            [go_plugin_build_result.output_digest, go_grpc_plugin_build_result.output_digest]
        ),
    )
    plugin_digest = await Get(Digest, RemovePrefix(merged_output_digests, "gopath/bin"))
    return SetupGoProtocPlugin(plugin_digest)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateGoFromProtobufRequest),
    )
