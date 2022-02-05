# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePath
from typing import DefaultDict

from pants.backend.codegen.thrift.target_types import AllThriftTargets, ThriftSourceField
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    FirstPartyPythonMappingImplMarker,
    ModuleProvider,
    ModuleProviderType,
)
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


def thrift_path_to_py_modules(source_path: str, *, namespace: str | None) -> tuple[str, str]:
    prefix = namespace if namespace else PurePath(source_path).stem
    return f"{prefix}.ttypes", f"{prefix}.constants"


class PythonThriftMappingMarker(FirstPartyPythonMappingImplMarker):
    pass


@rule(desc="Creating map of Thrift targets to generated Python modules", level=LogLevel.DEBUG)
async def map_thrift_to_python_modules(
    thrift_targets: AllThriftTargets,
    _: PythonThriftMappingMarker,
) -> FirstPartyPythonMappingImpl:
    modules_to_providers: DefaultDict[str, list[ModuleProvider]] = defaultdict(list)
    for tgt in thrift_targets:
        provider = ModuleProvider(tgt.address, ModuleProviderType.IMPL)
        # TODO: parse the namespace.
        m1, m2 = thrift_path_to_py_modules(
            source_path=tgt[ThriftSourceField].file_path, namespace=None
        )
        modules_to_providers[m1].append(provider)
        modules_to_providers[m2].append(provider)
    return FirstPartyPythonMappingImpl(
        (k, tuple(sorted(v))) for k, v in sorted(modules_to_providers.items())
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, PythonThriftMappingMarker),
    )
