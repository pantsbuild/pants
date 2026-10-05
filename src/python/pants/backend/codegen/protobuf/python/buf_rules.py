# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.codegen.protobuf.buf.generate import BufGenerateRequest, run_buf_generate
from pants.backend.codegen.protobuf.buf.generate import rules as buf_generate_rules
from pants.backend.codegen.protobuf.python.additional_fields import PythonSourceRootField
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    PythonProtobufSubsystem,
)
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import GeneratedSources, Target
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratePythonFromProtobufViaBufRequest:
    protocol_target: Target


@rule(desc="Generate Python from Protobuf via `buf generate`", level=LogLevel.DEBUG)
async def generate_python_from_protobuf_via_buf(
    request: GeneratePythonFromProtobufViaBufRequest,
    python_protobuf: PythonProtobufSubsystem,
) -> GeneratedSources:
    target = request.protocol_target

    if target.get(PythonSourceRootField).value is not None:
        logger.warning(
            "`python_source_root` is set on %s but `protobuf_generator='buf'`; "
            "the field is ignored — output paths come from the `out:` field of "
            "`buf.gen.yaml`.",
            target.address,
        )

    result = await run_buf_generate(
        BufGenerateRequest(
            target=target,
            language_template=python_protobuf.language_gen_template,
            description=f"Generating Python from Protobuf via buf for {target.address}.",
        ),
        **implicitly(),
    )
    return GeneratedSources(result.snapshot)


def rules():
    return [*collect_rules(), *buf_generate_rules()]
