# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import textwrap
from dataclasses import dataclass
from pathlib import PurePath

from pants.build_graph.address import Address
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.archive import ZipBinary
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestEntries,
    FileContent,
    FileEntry,
    MergeDigests,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Targets,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.target_types import (
    JvmWarContentField,
    JvmWarDependenciesField,
    JvmWarDescriptorAddressField,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PackageWarFileFieldSet(PackageFieldSet):
    required_fields = (
        JvmWarDependenciesField,
        JvmWarDescriptorAddressField,
    )

    output_path: OutputPathField
    dependencies: JvmWarDependenciesField
    descriptor: JvmWarDescriptorAddressField  # TODO: make required
    content: JvmWarContentField


@dataclass(frozen=True)
class RenderWarDeploymentDescriptorRequest:
    descriptor: JvmWarDescriptorAddressField
    owning_address: Address


@dataclass(frozen=True)
class RenderedWarDeploymentDescriptor:
    digest: Digest


@dataclass(frozen=True)
class RenderWarContentRequest:
    content: JvmWarContentField


@dataclass(frozen=True)
class RenderedWarContent:
    digest: Digest


@rule
async def package_war(
    field_set: PackageWarFileFieldSet,
    bash: BashBinary,
    zip: ZipBinary,
) -> BuiltPackage:
    classpath = await Get(Classpath, DependenciesRequest(field_set.dependencies))
    all_jar_files_digest = await Get(Digest, MergeDigests(classpath.digests()))

    prefixed_jars_digest, content, descriptor, make_archive_script_digest = await MultiGet(
        Get(Digest, AddPrefix(all_jar_files_digest, "__war__/WEB-INF/lib")),
        Get(RenderedWarContent, RenderWarContentRequest(field_set.content)),
        Get(
            RenderedWarDeploymentDescriptor,
            RenderWarDeploymentDescriptorRequest(field_set.descriptor, field_set.address),
        ),
        Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        "make_war.sh",
                        textwrap.dedent(
                            f"""\
                    mkdir -p __war__/WEB-INF/classes
                    cd __war__
                    {zip.path} ../output.war -r .
                    """
                        ).encode(),
                        is_executable=True,
                    )
                ]
            ),
        ),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                prefixed_jars_digest,
                descriptor.digest,
                content.digest,
                make_archive_script_digest,
            ]
        ),
    )

    result = await Get(
        ProcessResult,
        Process(
            [bash.path, "make_war.sh"],
            input_digest=input_digest,
            output_files=("output.war",),
            description=f"Assemble WAR file for {field_set.address}",
        ),
    )

    output_entries = await Get(DigestEntries, Digest, result.output_digest)
    if len(output_entries) != 1:
        raise AssertionError("No output from war assembly step.")
    output_entry = output_entries[0]
    if not isinstance(output_entry, FileEntry):
        raise AssertionError("Unexpected digest entry")
    output_filename = PurePath(field_set.output_path.value_or_default(file_ending="war"))
    package_digest = await Get(
        Digest, CreateDigest([FileEntry(str(output_filename), output_entry.file_digest)])
    )
    artifact = BuiltPackageArtifact(relpath=str(output_filename))
    return BuiltPackage(digest=package_digest, artifacts=(artifact,))


@rule
async def render_war_deployment_descriptor(
    request: RenderWarDeploymentDescriptorRequest,
) -> RenderedWarDeploymentDescriptor:
    if not request.descriptor.value:
        return RenderedWarDeploymentDescriptor(EMPTY_DIGEST)

    descriptor_addresses = await Get(
        Addresses,
        UnparsedAddressInputs([request.descriptor.value], owning_address=request.owning_address),
    )
    if not descriptor_addresses:
        return RenderedWarDeploymentDescriptor(EMPTY_DIGEST)

    wrapped_descriptor_target = await Get(WrappedTarget, Address, descriptor_addresses[0])
    descriptor_target = wrapped_descriptor_target.target

    descriptor_sources = await Get(
        HydratedSources,
        HydrateSourcesRequest(
            descriptor_target[SourcesField],
            for_sources_types=(FileSourceField, ResourceSourceField),
            enable_codegen=True,
        ),
    )

    descriptor_sources_contents = await Get(
        DigestContents, Digest, descriptor_sources.snapshot.digest
    )
    if len(descriptor_sources_contents) != 1:
        raise AssertionError("num source != 1")

    descriptor_digest = await Get(
        Digest,
        CreateDigest(
            [FileContent("__war__/WEB-INF/web.xml", descriptor_sources_contents[0].content)]
        ),
    )

    return RenderedWarDeploymentDescriptor(descriptor_digest)


@rule
async def render_war_content(request: RenderWarContentRequest) -> RenderedWarContent:
    addresses = await Get(
        Addresses, UnparsedAddressInputs, request.content.to_unparsed_address_inputs()
    )
    targets = await Get(Targets, Addresses, addresses)
    sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            [tgt[SourcesField] for tgt in targets if tgt.has_field(SourcesField)],
            for_sources_types=(ResourceSourceField, FileSourceField),
            enable_codegen=True,
        ),
    )
    digest = await Get(Digest, AddPrefix(sources.snapshot.digest, "__war__"))
    return RenderedWarContent(digest)


def rules():
    return (
        *collect_rules(),
        UnionRule(PackageFieldSet, PackageWarFileFieldSet),
    )
