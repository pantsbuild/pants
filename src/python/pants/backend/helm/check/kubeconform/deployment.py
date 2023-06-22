# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass
from itertools import chain

from pants.backend.helm.check.kubeconform.extra_fields import (
    KubeconformFieldSet,
    KubeconformIgnoreMissingSchemasField,
    KubeconformIgnoreSourcesField,
    KubeconformSkipField,
    KubeconformSkipKindsField,
)
from pants.backend.helm.check.kubeconform.standalone import KubeconformSubsystem
from pants.backend.helm.dependency_inference import deployment as infer_deployment
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.subsystems.post_renderer import HelmPostRenderer
from pants.backend.helm.target_types import HelmDeploymentFieldSet, HelmDeploymentTarget
from pants.backend.helm.util_rules import post_renderer, renderer
from pants.backend.helm.util_rules.post_renderer import HelmDeploymentPostRendererRequest
from pants.backend.helm.util_rules.renderer import (
    HelmDeploymentCmd,
    HelmDeploymentRequest,
    RenderedHelmFiles,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import CreateDigest, Digest, FileEntry
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KubeconformDeploymentFieldSet(HelmDeploymentFieldSet, KubeconformFieldSet):
    pass


_KUBECONFORM_CACHE_FOLDER = "__kubeconform_cache"


@dataclass(frozen=True)
class KubeconformSetup:
    binary: DownloadedExternalTool
    env: FrozenDict[str, str]

    @property
    def append_only_caches(self) -> dict[str, str]:
        return {"kubeconform": _KUBECONFORM_CACHE_FOLDER}


class KubeconformCheckDeploymentRequest(CheckRequest):
    field_set_type = KubeconformDeploymentFieldSet
    tool_name = KubeconformSubsystem.name


@dataclass(frozen=True)
class RunKubeconformOnHelmDeploymentRequest:
    field_set: KubeconformDeploymentFieldSet


@rule
async def setup_kube_conform(
    helm: HelmSubsystem,
    kubeconform: KubeconformSubsystem,
    platform: Platform,
) -> KubeconformSetup:
    downloaded_tool, env = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, kubeconform.get_request(platform)),
        Get(EnvironmentVars, EnvironmentVarsRequest(helm.extra_env_vars)),
    )
    return KubeconformSetup(downloaded_tool, env)


@rule
async def run_kubeconform_on_file(
    request: RunKubeconformOnHelmDeploymentRequest,
    setup: KubeconformSetup,
    kubeconform: KubeconformSubsystem,
) -> CheckResult:
    if request.field_set.skip.value:
        return CheckResult(
            exit_code=0, stdout="", stderr="", partition_description=request.field_set.address.spec
        )

    post_renderer = await Get(
        HelmPostRenderer, HelmDeploymentPostRendererRequest(request.field_set)
    )
    rendered_files = await Get(
        RenderedHelmFiles,
        HelmDeploymentRequest(
            request.field_set,
            cmd=HelmDeploymentCmd.RENDER,
            post_renderer=post_renderer,
            description=f"Evaluating Helm deployment files for {request.field_set.address}",
        ),
    )

    tool_relpath = "__kubeconform"
    chart_relpath = "__chart"
    immutable_input_digests = {
        tool_relpath: setup.binary.digest,
        chart_relpath: rendered_files.chart.snapshot.digest,
    }

    debug_requested = 0 < logger.getEffectiveLevel() <= LogLevel.DEBUG.level
    ignore_sources = request.field_set.ignore_sources.value or ()

    result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                os.path.join(tool_relpath, setup.binary.exe),
                "-cache",
                _KUBECONFORM_CACHE_FOLDER,
                *(("-n", str(kubeconform.concurrency)) if kubeconform.concurrency else ()),
                *(("-debug",) if debug_requested else ()),
                *(("-summary",) if kubeconform.summary else ()),
                *(("-verbose",) if kubeconform.verbose else ()),
                *(
                    ("-ignore-missing-schemas",)
                    if request.field_set.ignore_missing_schemas.value
                    else ()
                ),
                *chain.from_iterable(
                    ("-ignore-filename-pattern", shlex.quote(pattern)) for pattern in ignore_sources
                ),
                *chain.from_iterable(
                    ("-schema-location", shlex.quote(schema))
                    for schema in kubeconform.schema_locations
                ),
                *(
                    ("-skip", ",".join(request.field_set.skip_kinds.value))
                    if request.field_set.skip_kinds.value
                    else ()
                ),
                "-output",
                kubeconform.output_type.value,
                *(rendered_files.snapshot.files),
            ],
            env=setup.env,
            immutable_input_digests=immutable_input_digests,
            input_digest=rendered_files.snapshot.digest,
            append_only_caches=setup.append_only_caches,
            description=f"Validating Kubernetes manifests for {request.field_set.address}",
            level=LogLevel.DEBUG,
            cache_scope=ProcessCacheScope.SUCCESSFUL,
        ),
    )

    report_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileEntry(
                    path=f"{request.field_set.address.path_safe_spec}-kubeconform.stdout",
                    file_digest=result.stdout_digest,
                )
            ]
        ),
    )

    return CheckResult.from_fallible_process_result(
        result, partition_description=request.field_set.address.spec, report=report_digest
    )


@rule
async def run_check_deployment(
    request: KubeconformCheckDeploymentRequest,
    kubeconform: KubeconformSubsystem,
) -> CheckResults:
    check_results = await MultiGet(
        Get(
            CheckResult,
            RunKubeconformOnHelmDeploymentRequest(field_set),
        )
        for field_set in request.field_sets
    )
    return CheckResults(check_results, checker_name=kubeconform.name)


def rules():
    return [
        *collect_rules(),
        *infer_deployment.rules(),
        *post_renderer.rules(),
        *renderer.rules(),
        HelmDeploymentTarget.register_plugin_field(KubeconformSkipField),
        HelmDeploymentTarget.register_plugin_field(KubeconformIgnoreSourcesField),
        HelmDeploymentTarget.register_plugin_field(KubeconformIgnoreMissingSchemasField),
        HelmDeploymentTarget.register_plugin_field(KubeconformSkipKindsField),
        UnionRule(CheckRequest, KubeconformCheckDeploymentRequest),
    ]
