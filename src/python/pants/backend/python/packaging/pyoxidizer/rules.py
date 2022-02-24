# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass
from textwrap import dedent

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
from pants.engine.process import Process, ProcessResult
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
from pants.python.binaries import PythonBinary
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PyOxidizerFieldSet(PackageFieldSet):
    required_fields = (PyOxidizerDependenciesField,)

    entry_point: PyOxidizerEntryPointField
    dependencies: PyOxidizerDependenciesField
    unclassified_resources: PyOxidizerUnclassifiedResources
    template: PyOxidizerConfigSourceField


@dataclass(frozen=True)
class PyoxidizerRunnerScript:
    digest: Digest
    path: str

    CACHE_PATH = os.path.join(".cache", "pyoxidizer")


@rule
async def create_pyoxidizer_runner_script() -> PyoxidizerRunnerScript:
    # Note: PyOxidizer expects an absolute path for its cache dir, which can only be resolved
    # from within the execution sandbox. Thus, this code uses a script to resolve absolute paths.
    script = FileContent(
        "__run_pyoxidizer.py",
        dedent(
            f"""\
            import os, sys
            os.environ["PYOXIDIZER_CACHE_DIR"] = os.path.join(os.getcwd(), "{PyoxidizerRunnerScript.CACHE_PATH}")
            os.execv(sys.argv[1], sys.argv[1:])
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
    python: PythonBinary,
) -> BuiltPackage:
    direct_deps, pyoxidizer_pex = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.dependencies)),
        Get(
            Pex,
            PexRequest(
                output_filename="pyoxidizer.pex",
                internal_only=True,
                requirements=pyoxidizer.pex_requirements(),
                interpreter_constraints=pyoxidizer.interpreter_constraints,
                main=pyoxidizer.main,
            ),
        ),
    )

    deps_field_sets = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, [direct_deps[0]])
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
            argv=["build", *pyoxidizer.args],
            description=f"Building {field_set.address} with PyOxidizer",
            input_digest=input_digest,
            level=LogLevel.INFO,
            output_directories=["build"],
        ),
    )
    process_with_caching = dataclasses.replace(
        pex_process,
        argv=(python.path, runner_script.path, *pex_process.argv),
        append_only_caches={
            **pex_process.append_only_caches,
            "pyoxidizer": runner_script.CACHE_PATH,
        },
    )

    result = await Get(ProcessResult, Process, process_with_caching)
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
