# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.python.lint.pyupgrade.skip_field import SkipPyUpgradeField
from pants.backend.python.lint.pyupgrade.subsystem import PyUpgrade
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fix import FixResult, FixTargetsRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PyUpgradeFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPyUpgradeField).value


class PyUpgradeRequest(FixTargetsRequest):
    field_set_type = PyUpgradeFieldSet
    tool_subsystem = PyUpgrade
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Fix with pyupgrade", level=LogLevel.DEBUG)
async def pyupgrade_fix(request: PyUpgradeRequest.Batch, pyupgrade: PyUpgrade) -> FixResult:
    pyupgrade_pex = await Get(VenvPex, PexRequest, pyupgrade.to_pex_request())

    # NB: Pyupgrade isn't idempotent, but eventually converges. So keep running until it stops
    # changing code. See https://github.com/asottile/pyupgrade/issues/703
    # (Technically we could not do this. It doesn't break Pants since the next run on the CLI would
    # use the new file with the new digest. However that isn't the UX we want for our users.)
    input_digest = request.snapshot.digest
    for _ in range(10):  # Give the loop an upper bound to guard against infinite runs
        result = await Get(  # noqa: PNT30: this is inherently sequential
            FallibleProcessResult,
            VenvPexProcess(
                pyupgrade_pex,
                argv=(*pyupgrade.args, *request.files),
                input_digest=input_digest,
                output_files=request.files,
                description=f"Run pyupgrade on {pluralize(len(request.files), 'file')}.",
                level=LogLevel.DEBUG,
            ),
        )
        if input_digest == result.output_digest:
            # Nothing changed, either due to failure or because it is fixed
            break
        input_digest = result.output_digest
    else:
        logger.error(
            softwrap(
                """
                Pants ran Pyupgrade continuously on the code 10 times and it changed all 10.

                Pyupgrade is not idempotent, but should eventually converge. This is either a bug in
                Pyupgrade, or Pyupgrade is still trying to converge on fixed code.
                """
            )
        )

    return await FixResult.create(request, result)


def rules():
    return [
        *collect_rules(),
        *PyUpgradeRequest.rules(),
        *pex.rules(),
    ]
