# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict

from pants.backend.shell.lint.shellcheck.subsystem import Shellcheck
from pants.backend.shell.shell_setup import ShellSetup
from pants.backend.shell.target_types import ShellSources
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.addresses import Address
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    SourcesPaths,
    SourcesPathsRequest,
    Targets,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShellMapping:
    """A mapping of Shell file names to their owning file address."""

    mapping: FrozenDict[str, Address]
    ambiguous_modules: FrozenDict[str, tuple[Address, ...]]


@rule(desc="Creating map of Shell file names to Shell targets", level=LogLevel.DEBUG)
async def map_shell_files() -> ShellMapping:
    all_expanded_targets = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    shell_tgts = tuple(tgt for tgt in all_expanded_targets if tgt.has_field(ShellSources))
    sources_per_target = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt[ShellSources])) for tgt in shell_tgts
    )

    files_to_addresses: dict[str, Address] = {}
    files_with_multiple_owners: DefaultDict[str, set[Address]] = defaultdict(set)
    for tgt, sources in zip(shell_tgts, sources_per_target):
        for f in sources.files:
            if f in files_to_addresses:
                files_with_multiple_owners[f].update({files_to_addresses[f], tgt.address})
            else:
                files_to_addresses[f] = tgt.address

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
    # NB: We parse per-file, rather than per-target. This is necessary so that we can have each
    # file in complete isolation without its sibling files present so that Shellcheck errors when
    # trying to source a sibling file, which then allows us to extract that path.
    digest: Digest
    fp: str


PATH_FROM_SHELLCHECK_ERROR = re.compile(r"Not following: (.+) was not specified as input")


@rule
async def parse_shell_imports(
    request: ParseShellImportsRequest, shellcheck: Shellcheck
) -> ParsedShellImports:
    # We use Shellcheck to parse for us by running it against each file in isolation, which means
    # that all `source` statements will error. Then, we can extract the problematic paths from the
    # JSON output.
    downloaded_shellcheck = await Get(
        DownloadedExternalTool, ExternalToolRequest, shellcheck.get_request(Platform.current)
    )
    input_digest = await Get(Digest, MergeDigests([request.digest, downloaded_shellcheck.digest]))
    process_result = await Get(
        FallibleProcessResult,
        Process(
            # NB: We do not load up `[shellcheck].{args,config}` because it would risk breaking
            # determinism of dependency inference in an unexpected way.
            [downloaded_shellcheck.exe, "--format=json", request.fp],
            input_digest=input_digest,
            description=f"Detect Shell imports for {request.fp}",
            level=LogLevel.DEBUG,
            # We expect this to always fail, but it should still be cached because the process is
            # deterministic.
            cache_scope=ProcessCacheScope.ALWAYS,
        ),
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


class InferShellDependencies(InferDependenciesRequest):
    infer_from = ShellSources


@rule(desc="Inferring Shell dependencies by analyzing imports")
async def infer_shell_dependencies(
    request: InferShellDependencies, shell_mapping: ShellMapping, shell_setup: ShellSetup
) -> InferredDependencies:
    if not shell_setup.dependency_inference:
        return InferredDependencies([], sibling_dependencies_inferrable=False)

    address = request.sources_field.address
    wrapped_tgt = await Get(WrappedTarget, Address, address)
    explicitly_provided_deps, hydrated_sources = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(HydratedSources, HydrateSourcesRequest(request.sources_field)),
    )
    per_file_digests = await MultiGet(
        Get(Digest, DigestSubset(hydrated_sources.snapshot.digest, PathGlobs([f])))
        for f in hydrated_sources.snapshot.files
    )
    all_detected_imports = await MultiGet(
        Get(ParsedShellImports, ParseShellImportsRequest(digest, f))
        for digest, f in zip(per_file_digests, hydrated_sources.snapshot.files)
    )

    result: OrderedSet[Address] = OrderedSet()
    for detected_imports in all_detected_imports:
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
                maybe_disambiguated = explicitly_provided_deps.disambiguated_via_ignores(ambiguous)
                if maybe_disambiguated:
                    result.add(maybe_disambiguated)
    return InferredDependencies(sorted(result), sibling_dependencies_inferrable=True)


def rules():
    return (*collect_rules(), UnionRule(InferDependenciesRequest, InferShellDependencies))
