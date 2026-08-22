# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

import yaml

from pants.backend.helm.util_rules import docker_image_ref
from pants.backend.helm.util_rules.chart import HelmChart
from pants.backend.helm.util_rules.docker_image_ref import (
    ResolveDockerImageRefRequest,
    resolve_docker_image_ref,
)
from pants.engine.addresses import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    CreateDigest,
    DigestSubset,
    FileContent,
    MergeDigests,
    PathGlobs,
)
from pants.engine.internals.build_files import maybe_resolve_address
from pants.engine.internals.native_engine import AddressInput, AddressParseException
from pants.engine.intrinsics import (
    create_digest,
    digest_subset_to_digest,
    digest_to_snapshot,
    get_digest_contents,
)
from pants.engine.rules import collect_rules, implicitly, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


def _set_nested_value(data: dict, dot_path: str, value: str) -> None:
    """Set a value in a nested dict using dot-notation path."""
    keys = dot_path.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


@dataclass(frozen=True)
class ResolveHelmChartValuesRequest(EngineAwareParameter):
    """Request to resolve helm chart values, replacing Docker target addresses with image refs."""

    chart: HelmChart
    values: FrozenDict[str, str]
    spec_path: str

    def debug_hint(self) -> str | None:
        return self.chart.address.spec


@rule(desc="Resolve Helm chart values", level=LogLevel.DEBUG)
async def resolve_helm_chart_values(
    request: ResolveHelmChartValuesRequest,
) -> HelmChart:
    """Resolve chart values (replacing Docker targets with image refs) and inject into
    values.yaml."""
    resolved_values: dict[str, str] = {}

    for dot_path, value in request.values.items():
        try:
            address_input = AddressInput.parse(
                value,
                relative_to=request.spec_path,
                description_of_origin="the `values` field of a `helm_chart` target",
            )
        except AddressParseException:
            resolved_values[dot_path] = value
            continue

        maybe_addr = await maybe_resolve_address(address_input)
        if not isinstance(maybe_addr.val, Address):
            resolved_values[dot_path] = value
            continue

        result = await resolve_docker_image_ref(
            ResolveDockerImageRefRequest(maybe_addr.val),
            **implicitly(),
        )
        if result.ref:
            logger.debug(
                f"Resolved Docker image ref '{result.ref}' for value path '{dot_path}' "
                f"from target {maybe_addr.val}."
            )
            resolved_values[dot_path] = result.ref
        else:
            resolved_values[dot_path] = value

    chart = request.chart
    contents = await get_digest_contents(chart.snapshot.digest)

    values_content: bytes = b""
    values_filename = "values.yaml"
    for fc in contents:
        if fc.path == "values.yaml" or fc.path == "values.yml":
            values_content = fc.content
            values_filename = fc.path
            break

    existing_values = (yaml.safe_load(values_content) or {}) if values_content else {}
    for dot_path, value in resolved_values.items():
        _set_nested_value(existing_values, dot_path, value)

    new_values_content = yaml.safe_dump(existing_values, default_flow_style=False).encode("utf-8")

    without_values = await digest_subset_to_digest(
        DigestSubset(
            chart.snapshot.digest,
            PathGlobs(["**/*", f"!{values_filename}"]),
        )
    )
    new_values_digest = await create_digest(
        CreateDigest([FileContent(values_filename, new_values_content)])
    )
    new_snapshot = await digest_to_snapshot(
        **implicitly(MergeDigests([without_values, new_values_digest]))
    )

    return HelmChart(
        address=chart.address,
        info=chart.info,
        snapshot=new_snapshot,
        artifact=chart.artifact,
    )


def rules():
    return [
        *collect_rules(),
        *docker_image_ref.rules(),
    ]
