# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.docker.goals.package_image import DockerPackageFieldSet
from pants.backend.k8s.k8s_subsystem import K8sSubsystem
from pants.backend.k8s.kubectl_subsystem import Kubectl
from pants.backend.k8s.target_types import (
    K8sBundleContextField,
    K8sBundleDependenciesField,
    K8sBundleSourcesField,
    K8sSourceField,
)
from pants.core.goals.deploy import DeployFieldSet, DeployProcess
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.fs import MergeDigests
from pants.engine.internals.graph import hydrate_sources, resolve_targets
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.platform_rules import environment_vars_subset
from pants.engine.intrinsics import digest_to_snapshot
from pants.engine.platform import Platform
from pants.engine.process import InteractiveProcess, Process, ProcessCacheScope
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import DependenciesRequest, HydrateSourcesRequest, SourcesField
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

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


@dataclass(frozen=True)
class KubectlApply:
    paths: tuple[str, ...]
    input_digest: Digest
    platform: Platform
    env: FrozenDict[str, str] | None = None
    context: str | None = None


@rule(desc="Run k8s deploy process", level=LogLevel.DEBUG)
async def run_k8s_deploy(
    field_set: DeployK8sBundleFieldSet,
    kubectl: Kubectl,
    k8s_subsystem: K8sSubsystem,
    platform: Platform,
) -> DeployProcess:
    context = field_set.context.value
    if context is None:
        raise ValueError(
            f"Missing `{K8sBundleContextField.alias}` field on target `{field_set.address.spec}`"
        )

    context = context if kubectl.pass_context else None
    if context is not None and context not in k8s_subsystem.available_contexts:
        raise ValueError(
            f"Context `{context}` is not listed in `[{K8sSubsystem.options_scope}].available_contexts`"
        )

    dependencies = await resolve_targets(
        **implicitly(field_set.sources.to_unparsed_address_inputs())
    )
    file_sources = await concurrently(
        hydrate_sources(
            HydrateSourcesRequest(
                t.get(SourcesField),
                for_sources_types=(K8sSourceField,),
                enable_codegen=True,
            ),
            **implicitly(),
        )
        for t in dependencies
    )
    snapshot, target_dependencies = await concurrently(
        digest_to_snapshot(
            **implicitly(MergeDigests((*(sources.snapshot.digest for sources in file_sources),)))
        ),
        resolve_targets(**implicitly(DependenciesRequest(field_set.dependencies))),
    )

    publish_targets = [
        tgt for tgt in target_dependencies if DockerPackageFieldSet.is_applicable(tgt)
    ]

    env = await environment_vars_subset(
        **implicitly(
            {EnvironmentVarsRequest(requested=kubectl.extra_env_vars): EnvironmentVarsRequest}
        )
    )

    process = InteractiveProcess.from_process(
        await kubectl_apply_process(
            KubectlApply(
                snapshot.files,
                platform=platform,
                input_digest=snapshot.digest,
                env=env,
                context=context,
            ),
            **implicitly(),
        )
    )

    description = f"context {context}" if context is not None else None

    return DeployProcess(
        name=field_set.address.spec,
        publish_dependencies=tuple(publish_targets),
        process=process,
        description=description,
    )


@rule
async def kubectl_apply_process(
    request: KubectlApply, platform: Platform, kubectl: Kubectl
) -> Process:
    tool_relpath = "__kubectl"
    argv: tuple[str, ...] = (f"{tool_relpath}/kubectl",)

    if request.context is not None:
        argv += ("--context", request.context)

    argv += ("apply", "-o", "yaml")

    for path in request.paths:
        argv += ("-f", path)

    kubectl_tool = await download_external_tool(kubectl.get_request(platform))

    immutable_input_digests = {
        tool_relpath: kubectl_tool.digest,
    }

    return Process(
        argv=argv,
        input_digest=request.input_digest,
        cache_scope=ProcessCacheScope.PER_SESSION,
        description=f"Applying kubernetes config {request.paths}",
        env=request.env,
        immutable_input_digests=immutable_input_digests,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(DeployFieldSet, DeployK8sBundleFieldSet),
    ]
