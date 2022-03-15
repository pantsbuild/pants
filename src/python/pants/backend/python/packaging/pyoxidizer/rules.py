# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent

from pants.backend.python.packaging.pyoxidizer.config import PyOxidizerConfig
from pants.backend.python.packaging.pyoxidizer.subsystem import PyOxidizer
from pants.backend.python.packaging.pyoxidizer.target_types import (
    PyOxidizerConfigSourceField,
    PyOxidizerDependenciesField,
    PyOxidizerEntryPointField,
    PyOxidizerOutputPathField,
    PyOxidizerTarget,
    PyOxidizerUnclassifiedResources,
)
from pants.backend.python.target_types import GenerateSetupField, WheelField
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    HydratedSources,
    HydrateSourcesRequest,
    InvalidTargetException,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PyOxidizerFieldSet(PackageFieldSet):
    required_fields = (PyOxidizerDependenciesField,)

    entry_point: PyOxidizerEntryPointField
    dependencies: PyOxidizerDependenciesField
    unclassified_resources: PyOxidizerUnclassifiedResources
    template: PyOxidizerConfigSourceField
    output_path: PyOxidizerOutputPathField


@dataclass(frozen=True)
class PyoxidizerRunnerScript:
    digest: Digest
    path: str

    CACHE_PATH = os.path.join(".cache", "pyoxidizer")


@rule
async def create_pyoxidizer_runner_script() -> PyoxidizerRunnerScript:
    # Note: PyOxidizer expects an absolute path for its cache dir, which can only be resolved
    # from within the execution sandbox. Thus, this code uses a bash script to be able to resolve
    # absolute paths inside the sandbox.
    script = FileContent(
        "__run_pyoxidizer.sh",
        dedent(
            f"""\
            export PYOXIDIZER_CACHE_DIR="$(/bin/pwd)/{PyoxidizerRunnerScript.CACHE_PATH}"
            exec "$@"
            """
        ).encode("utf-8"),
    )
    digest = await Get(Digest, CreateDigest([script]))
    return PyoxidizerRunnerScript(digest, script.path)


@rule(level=LogLevel.DEBUG)
async def package_pyoxidizer_binary(
    pyoxidizer: PyOxidizer,
    field_set: PyOxidizerFieldSet,
    runner_script: PyoxidizerRunnerScript,
    bash: BashBinary,
) -> BuiltPackage:
    direct_deps = await Get(Targets, DependenciesRequest(field_set.dependencies))
    deps_field_sets = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, direct_deps)
    )
    built_packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set) for field_set in deps_field_sets.field_sets
    )
    wheel_paths = [
        artifact.relpath
        for built_pkg in built_packages
        for artifact in built_pkg.artifacts
        if artifact.relpath is not None and artifact.relpath.endswith(".whl")
    ]
    if not wheel_paths:
        raise InvalidTargetException(
            f"The `{PyOxidizerTarget.alias}` target {field_set.address} must include "
            "in its `dependencies` field at least one `python_distribution` target that produces a "
            f"`.whl` file. For example, if using `{GenerateSetupField.alias}=True`, then make sure "
            f"`{WheelField.alias}=True`. See {doc_url('python-distributions')}."
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

    pyoxidizer_pex, config_digest = await MultiGet(
        Get(Pex, PexRequest, pyoxidizer.to_pex_request()),
        Get(Digest, CreateDigest([FileContent("pyoxidizer.bzl", rendered_config.encode("utf-8"))])),
    )
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                config_digest,
                runner_script.digest,
                *(built_package.digest for built_package in built_packages),
            )
        ),
    )
    pex_process = await Get(
        Process,
        PexProcess(
            pyoxidizer_pex,
            argv=("build", *pyoxidizer.args),
            description=f"Building {field_set.address} with PyOxidizer",
            input_digest=input_digest,
            level=LogLevel.INFO,
            output_directories=("build",),
        ),
    )
    process_with_caching = dataclasses.replace(
        pex_process,
        argv=(bash.path, runner_script.path, *pex_process.argv),
        append_only_caches={
            **pex_process.append_only_caches,
            "pyoxidizer": runner_script.CACHE_PATH,
        },
    )

    result = await Get(ProcessResult, Process, process_with_caching)

    stripped_digest = await Get(Digest, RemovePrefix(result.output_digest, "build"))
    final_snapshot = await Get(
        Snapshot,
        AddPrefix(stripped_digest, field_set.output_path.value_or_default(file_ending=None)),
    )
    return BuiltPackage(
        final_snapshot.digest,
        artifacts=tuple(BuiltPackageArtifact(file) for file in final_snapshot.files),
    )


@rule
async def run_pyoxidizer_binary(field_set: PyOxidizerFieldSet) -> RunRequest:
    def is_executable_binary(artifact_relpath: str | None) -> bool:
        """After packaging, the PyOxidizer plugin will place the executable in a location like this:
        dist/{project}/{target_name}/{platform arch}/{compilation mode}/install/{binary name}

        {binary name} will default to `target_name`, but can be modified with a custom PyOxidizer template.

        e.g. dist/helloworld/helloworld-bin/x86_64-apple-darwin/debug/install/helloworld-bin.

        PyOxidizer will place associated libraries in {...}/install/lib

        To determine if the artifact we iterate over is the one we want to execute, we check that
        the file's parent dir is "install". There should only be one of these files.
        """
        if not artifact_relpath:
            return False

        artifact_path = PurePath(artifact_relpath)
        return artifact_path.parent.name == "install"

    binary = await Get(BuiltPackage, PackageFieldSet, field_set)
    executable_binaries = [
        artifact for artifact in binary.artifacts if is_executable_binary(artifact.relpath)
    ]

    assert len(executable_binaries) == 1, (
        "More than one executable binary discovered in the `install` directory, "
        "which is a bug in the PyOxidizer plugin. "
        "Please file a bug report at https://github.com/pantsbuild/pants/issues/new. "
        f"Enumerated executable binaries: {executable_binaries}"
    )

    artifact = executable_binaries[0]
    assert artifact.relpath is not None
    return RunRequest(digest=binary.digest, args=(os.path.join("{chroot}", artifact.relpath),))


def rules():
    return (
        *collect_rules(),
        UnionRule(PackageFieldSet, PyOxidizerFieldSet),
        UnionRule(RunFieldSet, PyOxidizerFieldSet),
    )
