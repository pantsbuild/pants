# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.codegen.protobuf.buf.config import gen_template_request_for_target
from pants.backend.codegen.protobuf.buf.generate import BufGenerateRequest, run_buf_generate
from pants.backend.codegen.protobuf.buf.generate import rules as buf_generate_rules
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.python.additional_fields import PythonSourceRootField
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    PythonProtobufSubsystem,
)
from pants.core.util_rules.config_files import find_config_file
from pants.engine.fs import EMPTY_SNAPSHOT
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
    buf: BufSubsystem,
) -> GeneratedSources:
    target = request.protocol_target

    # With no template for Python, the target isn't meant to generate Python: e.g. it's only
    # generated for TypeScript, but `export-codegen` asks every language.
    template_files = await find_config_file(
        gen_template_request_for_target(target, buf, python_protobuf.language_gen_template)
    )
    if not template_files.snapshot.files:
        return GeneratedSources(EMPTY_SNAPSHOT)

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
