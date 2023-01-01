# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePath
from typing import DefaultDict

from pants.backend.codegen.thrift import thrift_parser
from pants.backend.codegen.thrift.target_types import AllThriftTargets, ThriftSourceField
from pants.backend.codegen.thrift.thrift_parser import ParsedThrift, ParsedThriftRequest
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    FirstPartyPythonMappingImplMarker,
    ModuleProvider,
    ModuleProviderType,
    ResolveName,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.engine.rules import Get, MultiGet, collect_rules, rule
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
    python_setup: PythonSetup,
    _: PythonThriftMappingMarker,
) -> FirstPartyPythonMappingImpl:
    parsed_files = await MultiGet(
        Get(ParsedThrift, ParsedThriftRequest(tgt[ThriftSourceField])) for tgt in thrift_targets
    )

    resolves_to_modules_to_providers: DefaultDict[
        ResolveName, DefaultDict[str, list[ModuleProvider]]
    ] = defaultdict(lambda: defaultdict(list))
    for tgt, parsed in zip(thrift_targets, parsed_files):
        resolve = tgt[PythonResolveField].normalized_value(python_setup)
        provider = ModuleProvider(tgt.address, ModuleProviderType.IMPL)
        m1, m2 = thrift_path_to_py_modules(
            source_path=tgt[ThriftSourceField].file_path, namespace=parsed.namespaces.get("py")
        )
        resolves_to_modules_to_providers[resolve][m1].append(provider)
        resolves_to_modules_to_providers[resolve][m2].append(provider)

    return FirstPartyPythonMappingImpl.create(resolves_to_modules_to_providers)


def rules():
    return (
        *collect_rules(),
        *thrift_parser.rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, PythonThriftMappingMarker),
    )
