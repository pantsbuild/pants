# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations
import pkgutil
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent
from typing import cast
from pants.backend.python.target_types import PythonTestTarget, PythonTestsGeneratorTarget
from pants.backend.python.goals.pytest_runner import PytestPluginSetup, PytestPluginSetupRequest
from pants.engine.target import Target, Targets, StringField
from pants.engine.unions import UnionRule
from pants.engine.addresses import UnparsedAddressInputs
from functools import partial
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.backend.docker.goals.package_image import BuiltDockerImage, DockerFieldSet
from pants.backend.docker.util_rules.docker_binary import DockerBinary
from pants.engine.process import Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule

import logging
from pprint import pformat
logger = logging.getLogger(__name__)
from dataclasses import asdict
import dataclasses

_DOCKER_PYTHON_PACKAGE = "pants.backend.docker.python"
_DOCKER_SHIM_FILE = "docker_shim.sh"

class DockerRunPythonTests(StringField):
    alias = "run_in_container"
    help = (
        "Provide the target address to a `docker_image` that can run the tests."
    )


class RunInContainerRequest(PytestPluginSetupRequest):
    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        return bool(target.get(DockerRunPythonTests).value)

    @classmethod
    def preprocess(cls, process: Process, docker: DockerBinary, image_ref: str) -> Process:
        logger.info(f"\nPREPROCESS:\n{pformat(locals())}\n")
        argv = ("./docker_shim.sh", *process.env.keys(), "--", *process.argv)
        return dataclasses.replace(process, argv=argv)


@rule
async def setup_run_in_container(request: RunInContainerRequest, docker: DockerBinary) -> PytestPluginSetup:
    image_address = request.target[DockerRunPythonTests].value
    targets = await Get(Targets, UnparsedAddressInputs([image_address], owning_address=request.target.address))
    if len(targets) != 1:
        raise ValueError(f"Unknown `run_in_container` address {image_address!r} for {request.target.address}.")
    image_target = targets[0]
    if not DockerFieldSet.is_applicable(image_target):
        raise ValueError(f"Can not build Docker image from {image_target.address}")

    docker_shim_content = pkgutil.get_data(_DOCKER_PYTHON_PACKAGE, _DOCKER_SHIM_FILE)
    if not docker_shim_content:
        raise ValueError(
            "Unable to find source to {_DOCKER_SHIM_FILE!r} in {_DOCKER_PYTHON_PACKAGE}."
        )

    digest, image = await MultiGet(
        Get(Digest, CreateDigest([FileContent("docker_shim.sh", docker_shim_content, is_executable=True)]))
        Get(BuiltPackage, PackageFieldSet, DockerFieldSet.create(image_target)),
    )

    return PytestPluginSetup(
        digest=digest,
        preprocess_callback=partial(
            request.preprocess,
            docker=docker,
            image=cast(BuiltDockerImage, image.artifacts[0]).tags[0],
        )
    )


def rules():
    return (
        *collect_rules(),
        PythonTestsGeneratorTarget.register_plugin_field(DockerRunPythonTests),
        PythonTestTarget.register_plugin_field(DockerRunPythonTests),
        UnionRule(PytestPluginSetupRequest, RunInContainerRequest),
    )
