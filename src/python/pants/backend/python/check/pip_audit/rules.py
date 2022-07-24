# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from pants.backend.python.check.pip_audit.skip_field import SkipPipAuditField
from pants.backend.python.check.pip_audit.subsystem import PipAudit
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonRequirementResolveField, PythonRequirementsField
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.partition import ResolveName
from pants.backend.python.util_rules.pex import PexRequest, PexResolveInfo, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.base.build_root import BuildRoot
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.engine.collection import Collection
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.process import FallibleProcessResult, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PipAuditFieldSet(FieldSet):
    required_fields = (
        PythonRequirementsField,
        PythonRequirementResolveField,
    )

    resolve: PythonRequirementResolveField
    sources: PythonRequirementsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPipAuditField).value


@dataclass(frozen=True)
class PipAuditPartition:
    description: str
    field_sets: FrozenOrderedSet[PipAuditFieldSet]


class PipAuditPartitions(Collection[PipAuditPartition]):
    pass


class PipAuditRequest(CheckRequest):
    field_set_type = PipAuditFieldSet
    name = PipAudit.options_scope


@rule
async def pip_audit_partition(
    partition: PipAuditPartition,
    pip_audit: PipAudit,
    build_root: BuildRoot,
) -> CheckResult:
    requirements_pex_get = Get(
        VenvPex,
        RequirementsPexRequest(
            (fs.address for fs in partition.field_sets),
        ),
    )

    pip_audit_pex_get = Get(
        VenvPex,
        PexRequest,
        pip_audit.to_pex_request(),
    )

    requirements_pex, pip_audit_pex = await MultiGet(requirements_pex_get, pip_audit_pex_get)
    requirements_pex_info = await Get(PexResolveInfo, VenvPex, requirements_pex)
    requirements_str = "\n".join(
        "{}=={}".format(dist_info.project_name, dist_info.version)
        for dist_info in requirements_pex_info
    )
    requirements_digest = await Get(
        Digest,
        CreateDigest([FileContent("requirements.txt", requirements_str.encode())]),
    )

    cache_dir = f".cache/pip_audit_cache/{sha256(build_root.path.encode()).hexdigest()}"
    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            pip_audit_pex,
            argv=(
                "--cache-dir",
                cache_dir,
                "--no-deps",
                "--progress-spinner",
                "off",
                "--requirement",
                "requirements.txt",
                *pip_audit.args,
            ),
            description=f"Run pip-audit on {pluralize(len(requirements_pex_info), 'requirement')}.",
            level=LogLevel.DEBUG,
            input_digest=requirements_digest,
            cache_scope=ProcessCacheScope.PER_SESSION,
            append_only_caches={"pip_audit_cache": cache_dir},
        ),
    )

    def prep_output(s: bytes) -> str:
        # pip-audit outputs the following warning since our generated requirements.txt is missing hashes:
        #   --no-deps is supported, but users are encouraged to fully hash their pinned dependencies
        #   Consider using a tool like `pip-compile`: https://pip-tools.readthedocs.io/en/latest/#using-hashes
        # TODO: Add hashes somehow? Maybe using PEX CLI's `lock export`?
        return re.sub(r"WARNING:pip_audit\._cli:.+(\r|\n|\r\n)", "", s.decode())

    return CheckResult(
        exit_code=result.exit_code,
        stdout=prep_output(result.stdout),
        stderr=prep_output(result.stderr),
        partition_description=partition.description,
    )


@rule(desc="Determine if necessary to partition pip-audit input", level=LogLevel.DEBUG)
async def pip_audit_determine_partitions(
    request: PipAuditRequest,
    python_setup: PythonSetup,
) -> PipAuditPartitions:
    resolves: Mapping[ResolveName, OrderedSet[PipAuditFieldSet]] = defaultdict(lambda: OrderedSet())

    for fs in request.field_sets:
        resolve = fs.resolve.normalized_value(python_setup)
        resolves[resolve].add(fs)

    return PipAuditPartitions(
        PipAuditPartition(
            description=resolve,
            field_sets=FrozenOrderedSet(requirements),
        )
        for resolve, requirements in sorted(resolves.items())
    )


@rule(desc="Scanning requirements using pip-audit", level=LogLevel.DEBUG)
async def pip_audit_check(request: PipAuditRequest, pip_audit: PipAudit) -> CheckResults:
    if pip_audit.skip:
        return CheckResults([], checker_name=request.name)

    partitions = await Get(PipAuditPartitions, PipAuditRequest, request)
    partitioned_results = await MultiGet(
        Get(CheckResult, PipAuditPartition, partition) for partition in partitions
    )

    return CheckResults(partitioned_results, checker_name=request.name)


def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, PipAuditRequest),
        *pex_from_targets.rules(),
    ]
