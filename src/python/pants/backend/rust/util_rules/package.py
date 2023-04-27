# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.rust.target_types import RustPackageTarget
from pants.engine.rules import collect_rules, rule
from pants.engine.target import GenerateTargetsRequest, GeneratedTargets
from pants.engine.unions import UnionRule, UnionMembership
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class ResolvedRustPackage:
    pkg_id: str

    target_dir: str


class GenerateTargetsFromRustPackageRequest(GenerateTargetsRequest):
    generate_from = RustPackageTarget


@rule(desc="Generate `rust_crate` targets from `rust_package` target", level=LogLevel.DEBUG)
async def generate_targets_from_rust_package(
    request: GenerateTargetsFromRustPackageRequest,
    union_membership: UnionMembership,
) -> GeneratedTargets:

    return GeneratedTargets(request.generator)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromRustPackageRequest),
    )
