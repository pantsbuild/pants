# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo, DockerfileInfoRequest
from pants.backend.docker.target_types import DockerDependenciesField
from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies, Targets
from pants.engine.unions import UnionRule


class InjectDockerDependencies(InjectDependenciesRequest):
    inject_for = DockerDependenciesField


@rule
async def inject_docker_dependencies(request: InjectDockerDependencies) -> InjectedDependencies:
    """Inspects COPY instructions in the Dockerfile for references to known targets."""
    dockerfile_info = await Get(
        DockerfileInfo, DockerfileInfoRequest(request.dependencies_field.address)
    )
    targets = await Get(
        Targets,
        UnparsedAddressInputs(
            dockerfile_info.putative_target_addresses,
            owning_address=None,
        ),
    )

    referenced_targets = (tgt.address for tgt in targets if PexBinaryFieldSet.is_applicable(tgt))
    return InjectedDependencies(Addresses(referenced_targets))


def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectDockerDependencies),
    ]
