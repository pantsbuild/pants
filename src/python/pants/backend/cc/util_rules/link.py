# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.cc.target_types import CCLanguage
from pants.backend.cc.util_rules.toolchain import CCProcess
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkCCObjectsRequest:
    """Link CC objects into a library or executable."""

    input_digest: Digest
    output_name: str
    # TODO: Name?
    compile_language: CCLanguage
    link_type: str | None = None


@dataclass(frozen=True)
class LinkedCCObjects:
    """A linked CC library/binary stored in a `Digest`."""

    digest: Digest


@rule(desc="Create a library or executable from object files")
async def link_cc_objects(request: LinkCCObjectsRequest) -> LinkedCCObjects:

    # Get object files stored in digest
    snapshot = await Get(Snapshot, Digest, request.input_digest)

    argv = ["-o", request.output_name, *snapshot.files]
    if request.link_type:
        argv += [f"-{str(request.link_type)}"]

    link_result = await Get(
        FallibleProcessResult,
        CCProcess(
            args=tuple(argv),
            input_digest=request.input_digest,
            language=request.compile_language,
            description=f"Linking CC binary: {request.output_name}",
            output_files=(request.output_name,),
            level=LogLevel.DEBUG,
        ),
    )
    logger.debug(link_result.stderr)

    return LinkedCCObjects(link_result.output_digest)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
