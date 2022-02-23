# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass

from pants.backend.python.packaging.pyoxidizer.config import PyOxidizerConfig
from pants.backend.python.packaging.pyoxidizer.subsystem import PyOxidizer
from pants.backend.python.packaging.pyoxidizer.target_types import (
    PyOxidizerConfigSourceField,
    PyOxidizerDependenciesField,
    PyOxidizerEntryPointField,
    PyOxidizerUnclassifiedResources,
)
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PyOxidizerFieldSet(PackageFieldSet):
    required_fields = (PyOxidizerDependenciesField,)

    entry_point: PyOxidizerEntryPointField
    dependencies: PyOxidizerDependenciesField
    unclassified_resources: PyOxidizerUnclassifiedResources
    template: PyOxidizerConfigSourceField


@rule(level=LogLevel.DEBUG)
async def package_pyoxidizer_binary(
    pyoxidizer: PyOxidizer, field_set: PyOxidizerFieldSet
) -> BuiltPackage:
    logger.debug(f"Incoming package_pyoxidizer_binary field set: {field_set}")
    targets = await Get(Targets, DependenciesRequest(field_set.dependencies))
    target = targets[0]

    logger.debug(f"Received these targets inside pyox targets: {target.address.target_name}")

    packages = await Get(
        FieldSetsPerTarget,
        FieldSetsPerTargetRequest(PackageFieldSet, [target]),
    )
    logger.debug(f"Retrieved the following FieldSetsPerTarget {packages}")

    built_packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set) for field_set in packages.field_sets
    )

    wheels = [
        artifact.relpath
        for wheel in built_packages
        for artifact in wheel.artifacts
        if artifact.relpath is not None
    ]
    logger.debug(f"This is the built package retrieved {built_packages}")

    # Pulling this merged digests idea from the Docker plugin
    built_package_digests = [built_package.digest for built_package in built_packages]

    # Pip install pyoxidizer
    pyoxidizer_pex = await Get(
        Pex,
        PexRequest(
            output_filename="pyoxidizer.pex",
            internal_only=True,
            requirements=pyoxidizer.pex_requirements(),
            interpreter_constraints=pyoxidizer.interpreter_constraints,
            main=pyoxidizer.main,
        ),
    )

    config_template = None
    if field_set.template.value is not None:
        config_template_source = await Get(SourceFiles, SourceFilesRequest([field_set.template]))

        digest_contents = await Get(DigestContents, Digest, config_template_source.snapshot.digest)
        config_template = digest_contents[0].content.decode("utf-8")

    config = PyOxidizerConfig(
        executable_name=field_set.address.target_name,
        entry_point=field_set.entry_point.value,
        wheels=wheels,
        template=config_template,
        unclassified_resources=None
        if not field_set.unclassified_resources.value
        else list(field_set.unclassified_resources.value),
    )

    rendered_config = config.render()
    logger.debug(f"Rendered configuation to use -> {rendered_config}")
    config_digest = await Get(
        Digest,
        CreateDigest([FileContent("pyoxidizer.bzl", rendered_config.encode("utf-8"))]),
    )

    all_digests = (config_digest, *built_package_digests)
    merged_digest = await Get(Digest, MergeDigests(d for d in all_digests if d))
    merged_digest_snapshot = await Get(Snapshot, Digest, merged_digest)
    logger.debug(merged_digest_snapshot)

    result = await Get(
        ProcessResult,
        PexProcess(
            pyoxidizer_pex,
            argv=["build", *pyoxidizer.args],
            description="Running PyOxidizer build (...this can take a minute...)",
            input_digest=merged_digest,
            level=LogLevel.DEBUG,
            output_directories=["build"],
        ),
    )

    snapshot = await Get(Snapshot, Digest, result.output_digest)
    artifacts = [BuiltPackageArtifact(file) for file in snapshot.files]
    return BuiltPackage(
        result.output_digest,
        artifacts=tuple(artifacts),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(PackageFieldSet, PyOxidizerFieldSet),
    )
