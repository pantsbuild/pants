# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.python.util_rules.pex import Pex
from pants.engine.rules import Rule, collect_rules
from pants.engine.unions import UnionRule

from .elfdeps.rules import RequestPexELFInfo, elfdeps_analyze_pex
from .elfdeps.rules import rules as elfdeps_rules


@dataclass(frozen=True)
class RpmDependsFromPexRequest:
    target_pex: Pex


@dataclass(frozen=True)
class RpmDependsInfo:
    provides: tuple[str, ...]
    requires: tuple[str, ...]


@rule
async def rpm_depends_from_pex(request: RpmDependsFromPexRequest) -> RpmDependsInfo:
    pex_elf_info = await elfdeps_analyze_pex(RequestPexELFInfo(request.target_pex), **implicitly())
    return RpmDependsInfo(provides=pex_elf_info.provides, requires=pex_elf_info.requires)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *elfdeps_rules(),
        *collect_rules(),
    )
