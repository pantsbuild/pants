# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import DefaultDict

from pants.backend.shell.lint.shellcheck.subsystem import Shellcheck
from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.backend.shell.target_types import ShellDependenciesField, ShellSourceField
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.addresses import Address
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import Digest
from pants.engine.internals.graph import determine_explicitly_provided_dependencies, hydrate_sources
from pants.engine.intrinsics import execute_process
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Rule, collect_rules, concurrently, implicitly, rule
from pants.engine.target import (
    AllTargets,
    DependenciesRequest,
    FieldSet,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


class AllShellTargets(Targets):
    pass


@rule(desc="Find all Shell targets in project", level=LogLevel.DEBUG)
async def find_all_shell_targets(all_tgts: AllTargets) -> AllShellTargets:
    return AllShellTargets(tgt for tgt in all_tgts if tgt.has_field(ShellSourceField))


@dataclass(frozen=True)
class ShellMapping:
    """A mapping of Shell file names to their owning file address."""

    mapping: FrozenDict[str, Address]
    ambiguous_modules: FrozenDict[str, tuple[Address, ...]]


@rule(desc="Creating map of Shell file names to Shell targets", level=LogLevel.DEBUG)
async def map_shell_files(tgts: AllShellTargets) -> ShellMapping:
    files_to_addresses: dict[str, Address] = {}
    files_with_multiple_owners: DefaultDict[str, set[Address]] = defaultdict(set)
    for tgt in tgts:
        fp = tgt[ShellSourceField].file_path
        if fp in files_to_addresses:
            files_with_multiple_owners[fp].update({files_to_addresses[fp], tgt.address})
        else:
            files_to_addresses[fp] = tgt.address

    # Remove files with ambiguous owners.
    for ambiguous_f in files_with_multiple_owners:
        files_to_addresses.pop(ambiguous_f)

    return ShellMapping(
        mapping=FrozenDict(sorted(files_to_addresses.items())),
        ambiguous_modules=FrozenDict(
            (k, tuple(sorted(v))) for k, v in sorted(files_with_multiple_owners.items())
        ),
    )


class ParsedShellImports(DeduplicatedCollection):
    sort_input = True


@dataclass(frozen=True)
class ParseShellImportsRequest:
    digest: Digest
    fp: str


PATH_FROM_SHELLCHECK_ERROR = re.compile(r"Not following: (.+) was not specified as input")


@rule
async def parse_shell_imports(
    request: ParseShellImportsRequest, shellcheck: Shellcheck, platform: Platform
) -> ParsedShellImports:
    # We use Shellcheck to parse for us by running it against each file in isolation, which means
    # that all `source` statements will error. Then, we can extract the problematic paths from the
    # JSON output.
    downloaded_shellcheck = await download_external_tool(shellcheck.get_request(platform))

    immutable_input_key = "__shellcheck_tool"
    exe_path = os.path.join(immutable_input_key, downloaded_shellcheck.exe)

    process_result = await execute_process(
        Process(
            # NB: We do not load up `[shellcheck].{args,config}` because it would risk breaking
            # determinism of dependency inference in an unexpected way.
            [exe_path, "--format=json", request.fp],
            input_digest=request.digest,
            immutable_input_digests={immutable_input_key: downloaded_shellcheck.digest},
            description=f"Detect Shell imports for {request.fp}",
            level=LogLevel.DEBUG,
            # We expect this to always fail, but it should still be cached because the process is
            # deterministic.
            cache_scope=ProcessCacheScope.ALWAYS,
        ),
        **implicitly(),
    )

    try:
        output = json.loads(process_result.stdout)
    except json.JSONDecodeError:
        logger.error(
            f"Parsing {request.fp} for dependency inference failed because Shellcheck's output "
            f"could not be loaded as JSON. Please open a GitHub issue at "
            f"https://github.com/pantsbuild/pants/issues/new with this error message attached.\n\n"
            f"\nshellcheck version: {shellcheck.version}\n"
            f"process_result.stdout: {process_result.stdout.decode()}"
        )
        return ParsedShellImports()

    paths = set()
    for error in output:
        if not error.get("code", "") == 1091:
            continue
        msg = error.get("message", "")
        matches = PATH_FROM_SHELLCHECK_ERROR.match(msg)
        if matches:
            paths.add(matches.group(1))
        else:
            logger.error(
                f"Parsing {request.fp} for dependency inference failed because Shellcheck's error "
                f"message was not in the expected format. Please open a GitHub issue at "
                f"https://github.com/pantsbuild/pants/issues/new with this error message "
                f"attached.\n\n\nshellcheck version: {shellcheck.version}\n"
                f"error JSON entry: {error}"
            )
    return ParsedShellImports(paths)


@dataclass(frozen=True)
class ShellDependenciesInferenceFieldSet(FieldSet):
    required_fields = (ShellSourceField, ShellDependenciesField)

    source: ShellSourceField
    dependencies: ShellDependenciesField


class InferShellDependencies(InferDependenciesRequest):
    infer_from = ShellDependenciesInferenceFieldSet


@rule(desc="Inferring Shell dependencies by analyzing imports")
async def infer_shell_dependencies(
    request: InferShellDependencies, shell_mapping: ShellMapping, shell_setup: ShellSetup
) -> InferredDependencies:
    if not shell_setup.dependency_inference:
        return InferredDependencies([])

    address = request.field_set.address
    explicitly_provided_deps, hydrated_sources = await concurrently(
        determine_explicitly_provided_dependencies(
            **implicitly(DependenciesRequest(request.field_set.dependencies))
        ),
        hydrate_sources(HydrateSourcesRequest(request.field_set.source), **implicitly()),
    )
    assert len(hydrated_sources.snapshot.files) == 1

    detected_imports = await parse_shell_imports(
        ParseShellImportsRequest(
            hydrated_sources.snapshot.digest, hydrated_sources.snapshot.files[0]
        ),
        **implicitly(),
    )
    result: OrderedSet[Address] = OrderedSet()
    for import_path in detected_imports:
        unambiguous = shell_mapping.mapping.get(import_path)
        ambiguous = shell_mapping.ambiguous_modules.get(import_path)
        if unambiguous:
            result.add(unambiguous)
        elif ambiguous:
            explicitly_provided_deps.maybe_warn_of_ambiguous_dependency_inference(
                ambiguous,
                address,
                import_reference="file",
                context=f"The target {address} sources `{import_path}`",
            )
            maybe_disambiguated = explicitly_provided_deps.disambiguated(ambiguous)
            if maybe_disambiguated:
                result.add(maybe_disambiguated)
    return InferredDependencies(sorted(result))


def rules() -> Iterable[Rule | UnionRule]:
    return (*collect_rules(), UnionRule(InferDependenciesRequest, InferShellDependencies))
