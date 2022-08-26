# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from typing_extensions import Literal

from pants.backend.cc.subsystems.toolchain import CCToolchain, CCToolchainRequest
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkCCObjectsRequest:
    """Link CC objects into a library or executable."""

    input_digest: Digest
    output_name: str
    compile_language: Literal["c", "c++"]
    link_type: str | None = None


@dataclass(frozen=True)
class LinkedCCObjects:
    """A linked CC library/binary stored in a `Digest`."""

    digest: Digest


@rule(desc="Create a library or executable from object files")
async def link_cc_objects(request: LinkCCObjectsRequest) -> LinkedCCObjects:

    # Get object files stored in digest
    snapshot = await Get(Snapshot, Digest, request.input_digest)

    # Get the appropriate toolchain for the object files (should be C++ if any object files were compiled in C++)
    toolchain = await Get(CCToolchain, CCToolchainRequest(language=request.compile_language))

    argv = list(toolchain.link_argv) + ["-o", request.output_name, *snapshot.files]
    if request.link_type:
        argv += [f"-{str(request.link_type)}"]

    logger.debug(f"Linker args for {request.output_name}: {argv}")
    link_result = await Get(
        FallibleProcessResult,
        Process(
            argv=argv,
            input_digest=request.input_digest,
            description=f"Linking CC binary: {request.output_name}",
            output_files=(request.output_name,),
            level=LogLevel.DEBUG,
            env={"__PANTS_CC_COMPILER_FINGERPRINT": toolchain.compiler.fingerprint},
        ),
    )
    logger.debug(link_result.stderr)

    return LinkedCCObjects(link_result.output_digest)


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
