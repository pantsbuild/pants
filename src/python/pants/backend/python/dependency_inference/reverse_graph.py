# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""A hybrid, batched implementation of the reverse-dependency graph for first-party Python.

The default `map_addresses_to_dependents` resolves the dependencies of every target individually,
which fans out to tens of engine nodes per target and dominates `dependents` / `--changed-dependents`
on large repos. This backend computes the *same* reverse graph as a hybrid:

  * "simple" first-party `python_source` targets -- those whose dependencies come purely from import
    and `__init__.py` inference (no explicit `dependencies=`, no special-cased fields, no other
    inference backend applicable) -- are handled in batched passes: their sources are parsed
    natively (grouped by source root, and each unique file parsed once even when shared across
    parametrizations), then owners are looked up per `(module, resolve)`; and
  * every other target (generators, `pex_binary`/`python_distribution`, `conftest`-consuming tests,
    special-cased, or explicit-`dependencies=` targets) is resolved with the normal per-target
    `resolve_dependencies` rule, so its edges are always exactly correct.

Parametrized targets *are* batched: parametrization (e.g. by resolve) does not change a file's
content, so it is parsed once and its owners are resolved at each parametrization's own resolve.
Because inferred dependencies bypass `_fill_parameters` (only *explicit* deps are filled, and those
targets are routed per-target), the batched edges -- importer address from the target, owner address
straight from `map_module_to_address(module, resolve)` / the resolve-matched `__init__` owner -- are
exactly what the per-target inference produces.

It is opt-in (`[dependents-inference].use_batched_python`). The per-target partition uses the
production rule, and the batched partition reproduces import/`__init__` inference exactly (honoring
resolves and `[python-infer].ambiguity_resolution`), so the union equals the per-target graph. The
only behavior it does not replicate is *raising* for unowned imports under
`[python-infer].unowned_dependency_behavior = "error"`; in a repo with no unowned imports (the
prerequisite for that mode to be silent) the result is identical.
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import PurePath

from pants.backend.project_info.dependents import (
    AddressToDependents,
    MaybeReverseDependencyGraph,
    ReverseDependencyGraphImpl,
)
from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwnersRequest,
    map_module_to_address,
)
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsePythonDependenciesRequest,
    parse_python_dependencies,
)
from pants.backend.python.dependency_inference.rules import (
    InferInitDependencies,
    InferPythonImportDependencies,
)
from pants.backend.python.dependency_inference.subsystem import (
    AmbiguityResolution,
    InitFilesInference,
    PythonInferSubsystem,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField, PythonSourceField
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.addresses import Address
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import resolve_dependencies
from pants.engine.intrinsics import digest_to_snapshot, get_digest_contents, path_globs_to_digest
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import (
    AllUnexpandedTargets,
    AlwaysTraverseDeps,
    Dependencies,
    DependenciesRequest,
    InferDependenciesRequest,
    SpecialCasedDependencies,
    TargetTypesToGenerateTargetsRequests,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.source.source_root import SourceRootsRequest, get_source_roots
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet

# Dependency-inference backends whose edges the batched pass reproduces. A target to which any other
# `InferDependenciesRequest` applies (conftest, pex entry points, distributions, plugins) is routed
# to the per-target partition instead.
_REPRODUCED_INFERENCE = frozenset({InferPythonImportDependencies, InferInitDependencies})


class PythonReverseDependencyGraphImpl(ReverseDependencyGraphImpl):
    pass


@rule(desc="Map all targets to their dependents (batched, first-party Python)")
async def python_reverse_dependency_graph(
    request: PythonReverseDependencyGraphImpl,
    all_targets: AllUnexpandedTargets,
    union_membership: UnionMembership,
    python_infer: PythonInferSubsystem,
    python_setup: PythonSetup,
    target_types_to_generate_requests: TargetTypesToGenerateTargetsRequests,
) -> MaybeReverseDependencyGraph:
    all_inference = union_membership.get(InferDependenciesRequest)
    unreproduced = [req for req in all_inference if req not in _REPRODUCED_INFERENCE]

    def has_explicit_or_special_deps(tgt) -> bool:
        return bool(tgt.get(Dependencies).value) or any(
            isinstance(f, SpecialCasedDependencies) for f in tgt.field_values.values()
        )

    def is_batchable(tgt) -> bool:
        # A "simple" first-party python_source: its deps come only from import + __init__ inference,
        # both of which we reproduce. Parametrization is fine (the file is parsed once and resolved
        # per-resolve); explicit/special-cased deps are not (they go through `_fill_parameters` and
        # other handling), nor is any inference backend we don't reproduce.
        if not tgt.has_field(PythonSourceField):
            return False
        if has_explicit_or_special_deps(tgt):
            return False
        if any(req.infer_from.is_applicable(tgt) for req in unreproduced):
            return False
        return True

    def contributes_no_edges(tgt) -> bool:
        # A target with no explicit/special-cased deps, to which no dependency inference applies, and
        # which is not a generator (generators inject deps on their generated targets), resolves to
        # zero dependencies -- so it contributes nothing to the reverse graph and can be skipped
        # entirely rather than paying for a `resolve_dependencies` call (e.g. `file`, `resource`,
        # and `python_requirement` targets, which dominate large repos).
        if has_explicit_or_special_deps(tgt):
            return False
        if any(req.infer_from.is_applicable(tgt) for req in all_inference):
            return False
        if (
            target_types_to_generate_requests.is_generator(tgt)
            and not tgt.address.is_generated_target
        ):
            return False
        return True

    def resolve_of(tgt) -> str | None:
        return (
            tgt[PythonResolveField].normalized_value(python_setup)
            if tgt.has_field(PythonResolveField)
            else None
        )

    # Batched units: one (address, resolve, file_path) per batchable target. Several units can share
    # a file_path (parametrizations of the same source); the file is parsed once and each unit
    # contributes edges at its own resolve.
    batched_units: list[tuple[Address, str | None, str]] = []
    per_target_tgts = []
    for tgt in all_targets:
        if is_batchable(tgt) and (fp := tgt.get(PythonSourceField).file_path):
            batched_units.append((tgt.address, resolve_of(tgt), fp))
        elif not contributes_no_edges(tgt):
            # Targets that contribute no edges (no deps, no inference, not a generator) are dropped.
            per_target_tgts.append(tgt)

    address_to_dependents: defaultdict[Address, set[Address]] = defaultdict(set)

    # ---- Per-target partition: the production rule, exactly correct for every tricky case. ----
    if per_target_tgts:
        per_target_results = await concurrently(
            resolve_dependencies(
                DependenciesRequest(
                    tgt.get(Dependencies), should_traverse_deps_predicate=AlwaysTraverseDeps()
                ),
                **implicitly(),
            )
            for tgt in per_target_tgts
        )
        for tgt, deps in zip(per_target_tgts, per_target_results):
            for dep in deps:
                address_to_dependents[dep].add(tgt.address)

    if not batched_units:
        return MaybeReverseDependencyGraph(
            AddressToDependents(
                FrozenDict(
                    {a: FrozenOrderedSet(sorted(d)) for a, d in address_to_dependents.items()}
                )
            )
        )

    # Every first-party python_source file -> the (address, resolve) of each target owning it
    # (across parametrizations), for `__init__.py` ownership resolution.
    py_source_info: defaultdict[str, list[tuple[Address, str | None]]] = defaultdict(list)
    for tgt in all_targets:
        if tgt.has_field(PythonSourceField):
            fp = tgt.get(PythonSourceField).file_path
            if fp:
                py_source_info[fp].append((tgt.address, resolve_of(tgt)))

    # ---- Batched import inference ----
    if python_infer.imports:
        # Group unique source files by source root: parsing strips source roots, and two files in
        # *different* roots can strip to the same path (e.g. top-level `__init__.py`), which would
        # collide when parsed together. Parsing per source root keeps stripped paths unique.
        batched_paths = sorted({fp for (_, _, fp) in batched_units})
        source_roots = await get_source_roots(SourceRootsRequest.for_files(batched_paths))
        path_to_root = {p: str(source_roots.path_to_root[PurePath(p)].path) for p in batched_paths}
        root_to_paths: defaultdict[str, list[str]] = defaultdict(list)
        for path in batched_paths:
            root_to_paths[path_to_root[path]].append(path)

        roots = list(root_to_paths)
        digests = await concurrently(
            path_globs_to_digest(PathGlobs(tuple(root_to_paths[root]))) for root in roots
        )
        snapshots = await concurrently(digest_to_snapshot(d) for d in digests)
        parses = await concurrently(
            parse_python_dependencies(
                ParsePythonDependenciesRequest(SourceFiles(s, ())), **implicitly()
            )
            for s in snapshots
        )

        # file_path -> list of imported module strings (same for every parametrization of the file).
        path_to_imports: dict[str, list[str]] = {}
        for root, parsed in zip(roots, parses):
            stripped_to_path = {
                (path if root == "." else path[len(root) + 1 :]): path
                for path in root_to_paths[root]
            }
            for stripped, file_deps in parsed.path_to_deps.items():
                path = stripped_to_path.get(stripped)
                if path is not None and file_deps.imports:
                    path_to_imports[path] = list(file_deps.imports)

        # (importer_address, resolve, locality, modules) for every batched unit with imports.
        file_imports: list[tuple[Address, str | None, str, list[str]]] = [
            (addr, resolve, path_to_root[fp], path_to_imports[fp])
            for (addr, resolve, fp) in batched_units
            if fp in path_to_imports
        ]

        # Phase 1: resolve each (module, resolve) once, ignoring locality.
        mr_list = sorted(
            {(m, r) for (_, r, _, mods) in file_imports for m in mods},
            key=lambda x: (x[0], x[1] or ""),
        )
        mr_owners = dict(
            zip(
                mr_list,
                await concurrently(
                    map_module_to_address(PythonModuleOwnersRequest(m, r), **implicitly())
                    for (m, r) in mr_list
                ),
            )
        )
        # Phase 2: under `by_source_root`, ambiguous modules are disambiguated using the importer's
        # source root as locality (matching `resolve_parsed_dependencies`).
        mrl_owners: dict[tuple[str, str | None, str], object] = {}
        if python_infer.ambiguity_resolution == AmbiguityResolution.by_source_root:
            mrl_list = sorted(
                {
                    (m, resolve, locality)
                    for (_, resolve, locality, mods) in file_imports
                    for m in mods
                    if (o := mr_owners.get((m, resolve))) is not None
                    and not o.unambiguous
                    and o.ambiguous
                },
                key=lambda x: (x[0], x[1] or "", x[2]),
            )
            mrl_owners = dict(
                zip(
                    mrl_list,
                    await concurrently(
                        map_module_to_address(PythonModuleOwnersRequest(m, r, l), **implicitly())
                        for (m, r, l) in mrl_list
                    ),
                )
            )

        for importer, resolve, locality, mods in file_imports:
            for module in mods:
                owners = mrl_owners.get((module, resolve, locality)) or mr_owners.get(
                    (module, resolve)
                )
                if owners is None:
                    continue
                for owner in owners.unambiguous:
                    if owner != importer:
                        address_to_dependents[owner].add(importer)

    # ---- Batched `__init__.py` inference (resolve-aware), for the batched units. ----
    if python_infer.init_files is not InitFilesInference.never:
        init_candidates = [
            p for p in py_source_info if os.path.basename(p) in ("__init__.py", "__init__.pyi")
        ]
        if python_infer.init_files is InitFilesInference.content_only and init_candidates:
            contents = await get_digest_contents(
                **implicitly({PathGlobs(init_candidates): PathGlobs})
            )
            init_paths = {fc.path for fc in contents if fc.content.strip()}
        else:
            init_paths = set(init_candidates)
        for importer, importer_resolve, fp in batched_units:
            package = ""
            chain = [""]
            for component in os.path.dirname(fp).split(os.sep):
                package = os.path.join(package, component) if package else component
                chain.append(package)
            for pkg in chain:
                for name in ("__init__.py", "__init__.pyi"):
                    init_path = os.path.join(pkg, name) if pkg else name
                    if init_path == fp or init_path not in init_paths:
                        continue
                    # `infer_python_init_dependencies` only adds init owners in the same resolve.
                    for owner_addr, owner_resolve in py_source_info.get(init_path, ()):
                        if owner_resolve == importer_resolve and owner_addr != importer:
                            address_to_dependents[owner_addr].add(importer)

    return MaybeReverseDependencyGraph(
        AddressToDependents(
            FrozenDict(
                {
                    addr: FrozenOrderedSet(sorted(deps))
                    for addr, deps in address_to_dependents.items()
                }
            )
        )
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(ReverseDependencyGraphImpl, PythonReverseDependencyGraphImpl),
    ]
