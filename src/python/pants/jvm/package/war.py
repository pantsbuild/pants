# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.build_graph.address import Address
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.system_binaries import BashBinary, ZipBinary
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestEntries,
    DigestSubset,
    Directory,
    FileContent,
    FileEntry,
    MergeDigests,
    PathGlobs,
)
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.jvm.classpath import Classpath
from pants.jvm.shading.rules import ShadedJar, ShadeJarRequest
from pants.jvm.target_types import (
    JvmShadingRule,
    JvmWarContentField,
    JvmWarDependenciesField,
    JvmWarDescriptorAddressField,
    JvmWarShadingRulesField,
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
    descriptor: JvmWarDescriptorAddressField
    content: JvmWarContentField
    shading_rules: JvmWarShadingRulesField


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


async def _apply_shading_rules_to_classpath(
    classpath: Classpath, shading_rules: Iterable[JvmShadingRule] | None
) -> Digest:
    input_digest = await Get(Digest, MergeDigests(classpath.digests()))
    if not shading_rules:
        return input_digest

    jars_digest = await Get(Digest, DigestSubset(input_digest, PathGlobs(["**/*.jar"])))
    digest_entries = await Get(DigestEntries, Digest, jars_digest)
    jar_entries = [entry for entry in digest_entries if isinstance(entry, FileEntry)]
    if len(jar_entries) == 0:
        return EMPTY_DIGEST

    jar_digests = await MultiGet(Get(Digest, CreateDigest([entry])) for entry in jar_entries)
    shaded_jars = await MultiGet(
        Get(ShadedJar, ShadeJarRequest(path=entry.path, digest=digest, rules=shading_rules))
        for entry, digest in zip(jar_entries, jar_digests)
    )
    return await Get(Digest, MergeDigests([shaded.digest for shaded in shaded_jars]))


@rule
async def package_war(
    field_set: PackageWarFileFieldSet,
    bash: BashBinary,
    zip: ZipBinary,
) -> BuiltPackage:
    classpath = await Get(Classpath, DependenciesRequest(field_set.dependencies))
    all_jar_files_digest = await _apply_shading_rules_to_classpath(
        classpath, field_set.shading_rules.value
    )

    prefixed_jars_digest, content, descriptor, input_setup_digest = await MultiGet(
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
                            cd __war__
                            {zip.path} ../output.war -r .
                            """
                        ).encode(),
                        is_executable=True,
                    ),
                    Directory("__war__/WEB-INF/classes"),
                    Directory("__war__/WEB-INF/lib"),
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
                input_setup_digest,
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
    descriptor_sources = await Get(
        HydratedSources,
        HydrateSourcesRequest(request.descriptor),
    )

    descriptor_sources_entries = await Get(
        DigestEntries, Digest, descriptor_sources.snapshot.digest
    )
    if len(descriptor_sources_entries) != 1:
        raise AssertionError(
            f"Expected `descriptor` field for {request.descriptor.address} to only refer to one file."
        )
    descriptor_entry = descriptor_sources_entries[0]
    if not isinstance(descriptor_entry, FileEntry):
        raise AssertionError(
            f"Expected `descriptor` field for {request.descriptor.address} to produce a file."
        )

    descriptor_digest = await Get(
        Digest,
        CreateDigest([FileEntry("__war__/WEB-INF/web.xml", descriptor_entry.file_digest)]),
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
