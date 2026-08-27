# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Determine which third-party import paths a `go_mod`'s own code actually references.

This is the first half of import-scoped third-party target generation. The build list produced by
`go list -m all` over-approximates what a repo uses -- often by a lot, since MVS resolves at module
granularity -- so generating a target for every package of every listed module both explodes the
target count and forces a download of every module in the graph.

NB: the scan reads `.go` files straight from the filesystem rather than resolving `go_package`
targets. It has to: the only caller is `generate_targets_from_go_mod`, which *is* a target
generator, so touching the target graph here would reintroduce the rule-graph cycle already
documented by the `build_opts` TODO in `target_type_rules.py`.
"""

from __future__ import annotations

import logging
import os.path
from dataclasses import dataclass

import ijson

from pants.backend.go.util_rules.pkg_analyzer import PackageAnalyzerSetup
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import GlobMatchErrorBehavior, MergeDigests, PathGlobs
from pants.engine.intrinsics import (
    digest_to_snapshot,
    execute_process,
    get_digest_contents,
    merge_digests,
)
from pants.engine.process import Process
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirstPartyImportRootsRequest(EngineAwareParameter):
    """Scan the first-party Go sources owned by a `go_mod` for the imports they reference."""

    go_mod_address: Address
    go_mod_path: str
    cgo_enabled: bool

    def debug_hint(self) -> str:
        return self.go_mod_address.spec


@dataclass(frozen=True)
class FirstPartyImportRoots:
    """Import paths referenced by first-party code, before stdlib/module filtering."""

    import_paths: FrozenOrderedSet[str]


def _is_nested_module_path(path: str, base_dir: str, nested_module_dirs: frozenset[str]) -> bool:
    """Whether `path` belongs to a module nested inside `base_dir` rather than to it.

    A nested `go.mod` carves its subtree out of the parent module entirely -- `go list ./...` in the
    parent never descends into it -- so its sources must not contribute roots to the parent.
    """
    for nested_dir in nested_module_dirs:
        if nested_dir == base_dir:
            continue
        if path == nested_dir or path.startswith(f"{nested_dir}/"):
            return True
    return False


def _parse_tool_directives(go_mod_content: bytes) -> tuple[str, ...]:
    """Extract `tool` directives from a go.mod (Go 1.24+).

    A `tool` directive names an executable package the module depends on without any `.go` file
    importing it, which is precisely the modern replacement for the `tools.go` pattern. Missing
    these would drop targets the user explicitly asked for.

    Handles both the single-line form (`tool example.com/cmd/foo`) and the block form
    (`tool (\\n\\texample.com/cmd/foo\\n)`).
    """
    tools: list[str] = []
    in_block = False
    for raw_line in go_mod_content.decode(errors="replace").splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue
        if in_block:
            if line == ")":
                in_block = False
            else:
                tools.append(line)
            continue
        if line == "tool (":
            in_block = True
        elif line.startswith("tool ") or line.startswith("tool\t"):
            tools.append(line[len("tool") :].strip())
    return tuple(t for t in tools if t)


@rule(desc="Scan first-party Go sources for third-party imports", level=LogLevel.DEBUG)
async def determine_first_party_import_roots(
    request: FirstPartyImportRootsRequest,
    analyzer: PackageAnalyzerSetup,
) -> FirstPartyImportRoots:
    base_dir = os.path.dirname(request.go_mod_path)
    prefix = f"{base_dir}/" if base_dir else ""

    sources_snapshot, nested_mods_snapshot = await concurrently(
        digest_to_snapshot(
            **implicitly(
                # NB: no `description_of_origin` -- these globs may legitimately match nothing
                # (a `go_mod` with no first-party sources yet), so match errors stay ignored.
                PathGlobs([f"{prefix}**/*.go"])
            )
        ),
        digest_to_snapshot(**implicitly(PathGlobs([f"{prefix}**/go.mod"]))),
    )

    nested_module_dirs = frozenset(os.path.dirname(p) for p in nested_mods_snapshot.files)

    candidate_dirs = sorted(
        {
            os.path.dirname(f)
            for f in sources_snapshot.files
            if not _is_nested_module_path(os.path.dirname(f), base_dir, nested_module_dirs)
        }
    )

    import_paths: set[str] = set()

    if candidate_dirs:
        input_digest = await merge_digests(MergeDigests([sources_snapshot.digest, analyzer.digest]))
        # NB: the analyzer reports `AllImports` even for directories it considers invalid (a
        # `tools.go`-only directory errors with "no buildable Go source files"), so failures here
        # are expected and must not abort the scan. `execute_process` rather than
        # `execute_process_or_raise` for exactly that reason.
        result = await execute_process(
            Process(
                (analyzer.path, *(d or "." for d in candidate_dirs)),
                input_digest=input_digest,
                description=(
                    f"Scan {len(candidate_dirs)} first-party Go package(s) for imports "
                    f"({request.go_mod_address})"
                ),
                level=LogLevel.DEBUG,
                env={"CGO_ENABLED": "1" if request.cgo_enabled else "0"},
            ),
            **implicitly(),
        )

        if result.stdout:
            for pkg_json in ijson.items(result.stdout, "", multiple_values=True):
                import_paths.update(pkg_json.get("AllImports", ()))
                import_paths.update(pkg_json.get("AllTestImports", ()))

    go_mod_contents = await get_digest_contents(
        **implicitly(
            PathGlobs(
                [request.go_mod_path],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=(
                    f"the import-scoped target generation scan for {request.go_mod_address}"
                ),
            )
        )
    )
    for entry in go_mod_contents:
        import_paths.update(_parse_tool_directives(entry.content))

    return FirstPartyImportRoots(FrozenOrderedSet(sorted(import_paths)))


def rules():
    return collect_rules()
