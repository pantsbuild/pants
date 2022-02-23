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
    HydratedSources,
    HydrateSourcesRequest,
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
    targets = await Get(Targets, DependenciesRequest(field_set.dependencies))
    target = targets[0]

    packages = await Get(FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, [target]))

    built_packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set) for field_set in packages.field_sets
    )
    wheel_paths = [
        artifact.relpath
        for built_pkg in built_packages
        for artifact in built_pkg.artifacts
        if artifact.relpath is not None and artifact.relpath.endswith(".whl")
    ]

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
        config_template_source = await Get(
            HydratedSources, HydrateSourcesRequest(field_set.template)
        )
        digest_contents = await Get(DigestContents, Digest, config_template_source.snapshot.digest)
        config_template = digest_contents[0].content.decode("utf-8")

    config = PyOxidizerConfig(
        executable_name=field_set.address.target_name,
        entry_point=field_set.entry_point.value,
        wheels=wheel_paths,
        template=config_template,
        unclassified_resources=(
            None
            if not field_set.unclassified_resources.value
            else list(field_set.unclassified_resources.value)
        ),
    )

    rendered_config = config.render()
    logger.debug(f"Configuration used for {field_set.address}: {rendered_config}")
    config_digest = await Get(
        Digest,
        CreateDigest([FileContent("pyoxidizer.bzl", rendered_config.encode("utf-8"))]),
    )

    input_digest = await Get(
        Digest,
        MergeDigests((config_digest, *(built_package.digest for built_package in built_packages))),
    )
    result = await Get(
        ProcessResult,
        PexProcess(
            pyoxidizer_pex,
            argv=["build", *pyoxidizer.args],
            description=f"Building {field_set.address} with PyOxidizer",
            input_digest=input_digest,
            level=LogLevel.INFO,
            output_directories=["build"],
        ),
    )

    result_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return BuiltPackage(
        result.output_digest,
        artifacts=tuple(BuiltPackageArtifact(file) for file in result_snapshot.files),
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(PackageFieldSet, PyOxidizerFieldSet),
    )
