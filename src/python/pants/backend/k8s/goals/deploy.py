from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.docker.goals.package_image import DockerPackageFieldSet
from pants.core.goals.deploy import DeployFieldSet, DeployProcess
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import MergeDigests, Snapshot
from pants.engine.process import InteractiveProcess
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, HydratedSources, HydrateSourcesRequest, SourcesField, Targets
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

from experimental.k8s.k8s_subsystem import K8sSubsystem
from experimental.k8s.kubectl_subsystem import KubectlBinary, KubectlOptions
from experimental.k8s.targets import (
    K8sBundleContextField,
    K8sBundleDependenciesField,
    K8sBundleSourcesField,
    K8sSourceField,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployK8sBundleFieldSet(DeployFieldSet):
    required_fields = (
        K8sBundleSourcesField,
        K8sBundleContextField,
        K8sBundleDependenciesField,
    )
    sources: K8sBundleSourcesField
    context: K8sBundleContextField
    dependencies: K8sBundleDependenciesField


@rule(desc="Run k8s deploy process", level=LogLevel.DEBUG)
async def run_k8s_deploy(
    field_set: DeployK8sBundleFieldSet,
    kubectl: KubectlBinary,
    options: KubectlOptions,
    k8s_subsystem: K8sSubsystem,
) -> DeployProcess:
    context = field_set.context.value
    assert context is not None
    context = context if options.pass_context else None
    if context is not None and context not in options.available_contexts:
        raise ValueError(f"context {context} is not listed in `[kubectl].available_contexts`")

    dependencies = await Get(Targets, UnparsedAddressInputs, field_set.sources.to_unparsed_address_inputs())
    file_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                t.get(SourcesField),
                for_sources_types=(K8sSourceField,),
                enable_codegen=True,
            ),
        )
        for t in dependencies
    )
    snapshot, target_dependencies = await MultiGet(
        Get(
            Snapshot,
            MergeDigests((*(sources.snapshot.digest for sources in file_sources),)),
        ),
        Get(Targets, DependenciesRequest(field_set.dependencies)),
    )

    if k8s_subsystem.publish_dependencies:
        publish_targets = [tgt for tgt in target_dependencies if DockerPackageFieldSet.is_applicable(tgt)]
    else:
        publish_targets = []

    # TODO use KubectlOptions.EnvironmentAware
    env = await Get(
        EnvironmentVars,
        EnvironmentVarsRequest,
        EnvironmentVarsRequest(requested=["HOME", "KUBECONFIG", "KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT"]),
    )

    process = InteractiveProcess.from_process(
        kubectl.apply_configs(
            snapshot.files,
            input_digest=snapshot.digest,
            env=env,
            context=context,
        )
    )

    description = f"context {context}" if context is not None else None

    return DeployProcess(
        name=field_set.address.spec,
        publish_dependencies=tuple(publish_targets),
        process=process,
        description=description,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(DeployFieldSet, DeployK8sBundleFieldSet),
    ]
