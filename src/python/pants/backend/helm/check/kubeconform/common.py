# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from abc import ABCMeta
from dataclasses import dataclass
from itertools import chain

from pants.backend.helm.check.kubeconform.extra_fields import KubeconformFieldSet
from pants.backend.helm.check.kubeconform.subsystem import KubeconformSubsystem
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.util_rules.renderer import RenderedHelmFiles
from pants.core.goals.check import CheckRequest, CheckResult
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import CreateDigest, Digest, FileEntry
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


class KubeconformCheckRequest(CheckRequest, metaclass=ABCMeta):
    tool_name = KubeconformSubsystem.name


@dataclass(frozen=True)
class RunKubeconformRequest:
    field_set: KubeconformFieldSet
    rendered_files: RenderedHelmFiles


@dataclass(frozen=True)
class KubeconformSetup:
    binary: DownloadedExternalTool
    env: FrozenDict[str, str]

    @property
    def cache_dir(self) -> str:
        return "__kubeconform_cache"

    @property
    def append_only_caches(self) -> dict[str, str]:
        return {"kubeconform": self.cache_dir}


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
async def run_kubeconform(
    request: RunKubeconformRequest, setup: KubeconformSetup, kubeconform: KubeconformSubsystem
) -> CheckResult:
    tool_relpath = "__kubeconform"
    chart_relpath = "__chart"
    immutable_input_digests = {
        tool_relpath: setup.binary.digest,
        chart_relpath: request.rendered_files.chart.snapshot.digest,
    }

    debug_requested = 0 < logger.getEffectiveLevel() <= LogLevel.DEBUG.level
    ignore_sources = request.field_set.ignore_sources.value or ()

    result = await Get(
        FallibleProcessResult,
        Process(
            argv=[
                os.path.join(tool_relpath, setup.binary.exe),
                "-cache",
                setup.cache_dir,
                *(("-n", str(kubeconform.concurrency)) if kubeconform.concurrency else ()),
                *(("-debug",) if debug_requested else ()),
                *(("-summary",) if kubeconform.summary else ()),
                *(("-verbose",) if kubeconform.verbose else ()),
                *(("-strict",) if request.field_set.strict.value else ()),
                *(
                    ("-ignore-missing-schemas",)
                    if request.field_set.ignore_missing_schemas.value
                    else ()
                ),
                *chain.from_iterable(
                    ("-ignore-filename-pattern", pattern) for pattern in ignore_sources
                ),
                *chain.from_iterable(
                    ("-schema-location", schema) for schema in kubeconform.schema_locations
                ),
                *(
                    ("-kubernetes-version", request.field_set.kubernetes_version.value)
                    if request.field_set.kubernetes_version.value
                    else ()
                ),
                *(
                    ("-reject", ",".join(request.field_set.reject_kinds.value))
                    if request.field_set.reject_kinds.value
                    else ()
                ),
                *(
                    ("-skip", ",".join(request.field_set.skip_kinds.value))
                    if request.field_set.skip_kinds.value
                    else ()
                ),
                "-output",
                kubeconform.output_type.value,
                *(request.rendered_files.snapshot.files),
            ],
            env=setup.env,
            immutable_input_digests=immutable_input_digests,
            input_digest=request.rendered_files.snapshot.digest,
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


def rules():
    return collect_rules()
