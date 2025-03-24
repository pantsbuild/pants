# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.codegen.python_format_string.target_types import (
    PythonFormatStringOutputPathField,
    PythonFormatStringSourceField,
    PythonFormatStringValuesField,
)
from pants.backend.k8s.target_types import K8sSourceField
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
)
from pants.engine.unions import UnionRule


class GenerateK8sSourceFromPythonFormatStringRequest(GenerateSourcesRequest):
    input = PythonFormatStringSourceField
    output = K8sSourceField


@rule
async def generate_k8s_source(
    request: GenerateK8sSourceFromPythonFormatStringRequest,
) -> GeneratedSources:
    format_string_target = request.protocol_target
    hydrated_sources = await Get(
        HydratedSources, HydrateSourcesRequest(format_string_target[PythonFormatStringSourceField])
    )

    if len(hydrated_sources.snapshot.files) != 1:
        raise ValueError(f"Expected single source, got {hydrated_sources.snapshot.files}")

    values = format_string_target[PythonFormatStringValuesField].value
    if values is None:
        raise ValueError(f"`{PythonFormatStringValuesField.alias}` is required")

    contents = await Get(DigestContents, Digest, hydrated_sources.snapshot.digest)
    content = contents[0].content.decode("utf-8")
    try:
        rendered = content.format(**values)
    except KeyError as e:
        raise ValueError(
            f"Missing key in target `{format_string_target.address}`: {e}, provided values: {values}"
        ) from e
    except IndexError as e:
        raise ValueError(f"Failed to render target `{format_string_target.address}`") from e

    path = format_string_target[PythonFormatStringOutputPathField].value_or_default(
        file_ending="rendered"
    )
    snapshot = await Get(
        Snapshot,
        CreateDigest([FileContent(path=path, content=rendered.encode("utf-8"))]),
    )
    return GeneratedSources(snapshot)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateK8sSourceFromPythonFormatStringRequest),
    )
