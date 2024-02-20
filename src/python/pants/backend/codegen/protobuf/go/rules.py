# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
import re
import textwrap
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.target_types import (
    AllProtobufTargets,
    ProtobufGrpcToggleField,
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.go import target_type_rules
from pants.backend.go.dependency_inference import (
    GoImportPathsMappingAddressSet,
    GoModuleImportPathsMapping,
    GoModuleImportPathsMappings,
    GoModuleImportPathsMappingsHook,
)
from pants.backend.go.target_type_rules import GoImportPathMappingRequest
from pants.backend.go.target_types import GoOwningGoModAddressField, GoPackageSourcesField
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    FallibleBuildGoPackageRequest,
)
from pants.backend.go.util_rules.build_pkg_target import (
    BuildGoPackageTargetRequest,
    GoCodegenBuildRequest,
)
from pants.backend.go.util_rules.first_party_pkg import FallibleFirstPartyPkgAnalysis
from pants.backend.go.util_rules.go_mod import OwningGoMod, OwningGoModRequest
from pants.backend.go.util_rules.pkg_analyzer import PackageAnalyzerSetup
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.backend.python.util_rules import pex
from pants.build_graph.address import Address
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesPaths,
    SourcesPathsRequest,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import (
    SourceRoot,
    SourceRootRequest,
    SourceRootsRequest,
    SourceRootsResult,
)
from pants.util.dirutil import group_by_dir
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

_logger = logging.getLogger(__name__)


class GoCodegenBuildProtobufRequest(GoCodegenBuildRequest):
    generate_from = ProtobufSourceField


class GenerateGoFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSourceField
    output = GoPackageSourcesField


@dataclass(frozen=True)
class _SetupGoProtocPlugin:
    digest: Digest


_QUOTE_CHAR = r"(?:'|\")"
_IMPORT_PATH_RE = re.compile(rf"^\s*option\s+go_package\s+=\s+{_QUOTE_CHAR}(.*){_QUOTE_CHAR};")


def parse_go_package_option(content_raw: bytes) -> str | None:
    content = content_raw.decode()
    for line in content.splitlines():
        m = _IMPORT_PATH_RE.match(line)
        if m:
            return m.group(1)
    return None


class ProtobufGoModuleImportPathsMappingsHook(GoModuleImportPathsMappingsHook):
    pass


@rule(desc="Map import paths for all Go Protobuf targets.", level=LogLevel.DEBUG)
async def map_import_paths_of_all_go_protobuf_targets(
    _request: ProtobufGoModuleImportPathsMappingsHook,
    all_protobuf_targets: AllProtobufTargets,
) -> GoModuleImportPathsMappings:
    sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                tgt[ProtobufSourceField],
                for_sources_types=(ProtobufSourceField,),
                enable_codegen=True,
            ),
        )
        for tgt in all_protobuf_targets
    )

    all_contents = await MultiGet(
        Get(DigestContents, Digest, source.snapshot.digest) for source in sources
    )

    go_protobuf_mapping_metadata = []
    owning_go_mod_gets = []
    for tgt, contents in zip(all_protobuf_targets, all_contents):
        if not contents:
            continue
        if len(contents) > 1:
            raise AssertionError(
                f"Protobuf target `{tgt.address}` mapped to more than one source file."
            )

        import_path = parse_go_package_option(contents[0].content)
        if not import_path:
            continue

        owning_go_mod_gets.append(Get(OwningGoMod, OwningGoModRequest(tgt.address)))
        go_protobuf_mapping_metadata.append((import_path, tgt.address))

    owning_go_mod_targets = await MultiGet(owning_go_mod_gets)

    import_paths_by_module: dict[Address, dict[str, set[Address]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for owning_go_mod, (import_path, address) in zip(
        owning_go_mod_targets, go_protobuf_mapping_metadata
    ):
        import_paths_by_module[owning_go_mod.address][import_path].add(address)

    return GoModuleImportPathsMappings(
        FrozenDict(
            {
                go_mod_addr: GoModuleImportPathsMapping(
                    mapping=FrozenDict(
                        {
                            import_path: GoImportPathsMappingAddressSet(
                                addresses=tuple(sorted(addresses)), infer_all=True
                            )
                            for import_path, addresses in import_path_mapping.items()
                        }
                    ),
                    address_to_import_path=FrozenDict(
                        {
                            address: import_path
                            for import_path, addresses in import_path_mapping.items()
                            for address in addresses
                        }
                    ),
                )
                for go_mod_addr, import_path_mapping in import_paths_by_module.items()
            }
        )
    )


@dataclass(frozen=True)
class _SetupGoProtobufPackageBuildRequest:
    """Request type used to trigger setup of a BuildGoPackageRequest for entire generated Go
    Protobuf package.

    This type is separate so that a build of the full package can be cached no matter which one of
    its component source files was requested. This occurs because a request to build any one of the
    source files will be converted into this type and then built.
    """

    addresses: tuple[Address, ...]
    import_path: str
    build_opts: GoBuildOptions


@rule
async def setup_full_package_build_request(
    request: _SetupGoProtobufPackageBuildRequest,
    protoc: Protoc,
    go_protoc_plugin: _SetupGoProtocPlugin,
    analyzer: PackageAnalyzerSetup,
    platform: Platform,
) -> FallibleBuildGoPackageRequest:
    output_dir = "_generated_files"
    protoc_relpath = "__protoc"
    protoc_go_plugin_relpath = "__protoc_gen_go"

    transitive_targets, downloaded_protoc_binary, empty_output_dir = await MultiGet(
        Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses)),
        Get(DownloadedExternalTool, ExternalToolRequest, protoc.get_request(platform)),
        Get(Digest, CreateDigest([Directory(output_dir)])),
    )

    go_mod_addr = await Get(OwningGoMod, OwningGoModRequest(transitive_targets.roots[0].address))
    package_mapping = await Get(
        GoModuleImportPathsMapping, GoImportPathMappingRequest(go_mod_addr.address)
    )

    all_sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=(
                tgt[ProtobufSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ProtobufSourceField)
            ),
            for_sources_types=(ProtobufSourceField,),
            enable_codegen=True,
        ),
    )
    source_roots, input_digest = await MultiGet(
        Get(SourceRootsResult, SourceRootsRequest, SourceRootsRequest.for_files(all_sources.files)),
        Get(Digest, MergeDigests([all_sources.snapshot.digest, empty_output_dir])),
    )

    source_root_paths = sorted({sr.path for sr in source_roots.path_to_root.values()})

    pkg_sources = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt[ProtobufSourceField]))
        for tgt in transitive_targets.roots
    )
    pkg_files = sorted({f for ps in pkg_sources for f in ps.files})

    maybe_grpc_plugin_args = []
    if any(tgt.get(ProtobufGrpcToggleField).value for tgt in transitive_targets.roots):
        maybe_grpc_plugin_args = [
            f"--go-grpc_out={output_dir}",
            "--go-grpc_opt=paths=source_relative",
        ]

    gen_result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                os.path.join(protoc_relpath, downloaded_protoc_binary.exe),
                f"--plugin=go={os.path.join('.', protoc_go_plugin_relpath, 'protoc-gen-go')}",
                f"--plugin=go-grpc={os.path.join('.', protoc_go_plugin_relpath, 'protoc-gen-go-grpc')}",
                f"--go_out={output_dir}",
                "--go_opt=paths=source_relative",
                *(f"--proto_path={source_root}" for source_root in source_root_paths),
                *maybe_grpc_plugin_args,
                *pkg_files,
            ],
            # Note: Necessary or else --plugin option needs absolute path.
            env={"PATH": protoc_go_plugin_relpath},
            input_digest=input_digest,
            immutable_input_digests={
                protoc_relpath: downloaded_protoc_binary.digest,
                protoc_go_plugin_relpath: go_protoc_plugin.digest,
            },
            description=f"Generating Go sources from {request.import_path}.",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
        ),
    )
    if gen_result.exit_code != 0:
        return FallibleBuildGoPackageRequest(
            request=None,
            import_path=request.import_path,
            exit_code=gen_result.exit_code,
            stderr=gen_result.stderr.decode(),
        )

    # Ensure that the generated files are in a single package directory.
    gen_sources = await Get(Snapshot, Digest, gen_result.output_digest)
    files_by_dir = group_by_dir(gen_sources.files)
    if len(files_by_dir) != 1:
        return FallibleBuildGoPackageRequest(
            request=None,
            import_path=request.import_path,
            exit_code=1,
            stderr=textwrap.dedent(
                f"""
                Expected Go files generated from Protobuf sources to be output to a single directory.
                - import path: {request.import_path}
                - protobuf files: {', '.join(pkg_files)}
                """
            ).strip(),
        )
    gen_dir = list(files_by_dir.keys())[0]

    # Analyze the generated sources.
    input_digest = await Get(Digest, MergeDigests([gen_sources.digest, analyzer.digest]))
    result = await Get(
        FallibleProcessResult,
        Process(
            (analyzer.path, gen_dir),
            input_digest=input_digest,
            description=f"Determine metadata for generated Go package for {request.import_path}",
            level=LogLevel.DEBUG,
            env={"CGO_ENABLED": "0"},  # protobuf files should not have cgo!
        ),
    )

    # Parse the metadata from the analysis.
    fallible_analysis = FallibleFirstPartyPkgAnalysis.from_process_result(
        result,
        dir_path=gen_dir,
        import_path=request.import_path,
        minimum_go_version="",
        description_of_source=f"Go package generated from protobuf targets `{', '.join(str(addr) for addr in request.addresses)}`",
    )
    if not fallible_analysis.analysis:
        return FallibleBuildGoPackageRequest(
            request=None,
            import_path=request.import_path,
            exit_code=fallible_analysis.exit_code,
            stderr=fallible_analysis.stderr,
        )
    analysis = fallible_analysis.analysis

    # Obtain build requests for third-party dependencies.
    # TODO: Consider how to merge this code with existing dependency inference code.
    dep_build_request_addrs: set[Address] = set()
    for dep_import_path in (*analysis.imports, *analysis.test_imports, *analysis.xtest_imports):
        # Infer dependencies on other Go packages.
        candidate_addresses = package_mapping.mapping.get(dep_import_path)
        if candidate_addresses:
            # TODO: Use explicit dependencies to disambiguate? This should never happen with Go backend though.
            if candidate_addresses.infer_all:
                dep_build_request_addrs.update(candidate_addresses.addresses)
            else:
                if len(candidate_addresses.addresses) > 1:
                    return FallibleBuildGoPackageRequest(
                        request=None,
                        import_path=request.import_path,
                        exit_code=result.exit_code,
                        stderr=textwrap.dedent(
                            f"""
                            Multiple addresses match import of `{dep_import_path}`.

                            addresses: {', '.join(str(a) for a in candidate_addresses.addresses)}
                            """
                        ).strip(),
                    )
                dep_build_request_addrs.update(candidate_addresses.addresses)

    dep_build_requests = await MultiGet(
        Get(BuildGoPackageRequest, BuildGoPackageTargetRequest(addr, build_opts=request.build_opts))
        for addr in sorted(dep_build_request_addrs)
    )

    return FallibleBuildGoPackageRequest(
        request=BuildGoPackageRequest(
            import_path=request.import_path,
            pkg_name=analysis.name,
            digest=gen_sources.digest,
            dir_path=analysis.dir_path,
            go_files=analysis.go_files,
            s_files=analysis.s_files,
            direct_dependencies=dep_build_requests,
            minimum_go_version=analysis.minimum_go_version,
            build_opts=request.build_opts,
        ),
        import_path=request.import_path,
    )


@rule
async def setup_build_go_package_request_for_protobuf(
    request: GoCodegenBuildProtobufRequest,
) -> FallibleBuildGoPackageRequest:
    # Hydrate the protobuf source to parse for the Go import path.
    sources = await Get(HydratedSources, HydrateSourcesRequest(request.target[ProtobufSourceField]))
    sources_content = await Get(DigestContents, Digest, sources.snapshot.digest)
    assert len(sources_content) == 1
    import_path = parse_go_package_option(sources_content[0].content)
    if not import_path:
        return FallibleBuildGoPackageRequest(
            request=None,
            import_path="",
            exit_code=1,
            stderr=f"No import path was set in Protobuf file via `option go_package` directive for {request.target.address}.",
        )

    go_mod_addr = await Get(OwningGoMod, OwningGoModRequest(request.target.address))
    package_mapping = await Get(
        GoModuleImportPathsMapping, GoImportPathMappingRequest(go_mod_addr.address)
    )

    # Request the full build of the package. This indirection is necessary so that requests for two or more
    # Protobuf files in the same Go package result in a single cacheable rule invocation.
    protobuf_target_addrs_set_for_import_path = package_mapping.mapping.get(import_path)
    if not protobuf_target_addrs_set_for_import_path:
        return FallibleBuildGoPackageRequest(
            request=None,
            import_path=import_path,
            exit_code=1,
            stderr=softwrap(
                f"""
                No Protobuf files exists for import path `{import_path}`.
                Consider whether the import path was set correctly via the `option go_package` directive.
                """
            ),
        )

    return await Get(
        FallibleBuildGoPackageRequest,
        _SetupGoProtobufPackageBuildRequest(
            addresses=protobuf_target_addrs_set_for_import_path.addresses,
            import_path=import_path,
            build_opts=request.build_opts,
        ),
    )


@rule(desc="Generate Go source files from Protobuf", level=LogLevel.DEBUG)
async def generate_go_from_protobuf(
    request: GenerateGoFromProtobufRequest,
    protoc: Protoc,
    go_protoc_plugin: _SetupGoProtocPlugin,
    platform: Platform,
) -> GeneratedSources:
    output_dir = "_generated_files"
    protoc_relpath = "__protoc"
    protoc_go_plugin_relpath = "__protoc_gen_go"

    downloaded_protoc_binary, empty_output_dir, transitive_targets = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, protoc.get_request(platform)),
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
        Digest, MergeDigests([all_sources_stripped.snapshot.digest, empty_output_dir])
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
# making sure to replace tabs with `\t`.

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
async def setup_go_protoc_plugin() -> _SetupGoProtocPlugin:
    go_mod_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent("go.mod", GO_PROTOBUF_GO_MOD.encode()),
                FileContent("go.sum", GO_PROTOBUF_GO_SUM.encode()),
            ]
        ),
    )

    # Called for the side effect downloading modules to the local cache
    await Get(
        ProcessResult,
        GoSdkProcess(
            ["mod", "download", "all"],
            input_digest=go_mod_digest,
            description="Download Go `protoc` plugin sources.",
            allow_downloads=True,
            cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
        ),
    )

    go_plugin_build_result, go_grpc_plugin_build_result = await MultiGet(
        Get(
            ProcessResult,
            GoSdkProcess(
                [
                    "install",
                    "google.golang.org/protobuf/cmd/protoc-gen-go@v1.27.1",
                ],
                output_files=["gobin/protoc-gen-go"],
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
                output_files=["gobin/protoc-gen-go-grpc"],
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
    plugin_digest = await Get(Digest, RemovePrefix(merged_output_digests, "gobin"))

    return _SetupGoProtocPlugin(plugin_digest)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateGoFromProtobufRequest),
        UnionRule(GoCodegenBuildRequest, GoCodegenBuildProtobufRequest),
        UnionRule(GoModuleImportPathsMappingsHook, ProtobufGoModuleImportPathsMappingsHook),
        ProtobufSourcesGeneratorTarget.register_plugin_field(GoOwningGoModAddressField),
        ProtobufSourceTarget.register_plugin_field(GoOwningGoModAddressField),
        # Rules needed for this to pass src/python/pants/init/load_backends_integration_test.py:
        *assembly.rules(),
        *build_pkg.rules(),
        *build_pkg_target.rules(),
        *first_party_pkg.rules(),
        *go_mod.rules(),
        *link.rules(),
        *sdk.rules(),
        *target_type_rules.rules(),
        *third_party_pkg.rules(),
        *pex.rules(),
    )
