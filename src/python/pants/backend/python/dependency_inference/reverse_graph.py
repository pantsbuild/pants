# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""A batched implementation of the reverse-dependency graph for first-party Python.

The default `map_addresses_to_dependents` resolves the dependencies of every target individually,
which fans out to tens of engine nodes per target and dominates `dependents` / `--changed-dependents`
on large repos. This backend computes the same reverse graph with a handful of batched passes:

  * generator -> generated-target edges, derived directly from the target set;
  * explicit `dependencies=[...]`, reusing `determine_explicitly_provided_dependencies`;
  * first-party import inference, via a single native parse of all sources + one owner lookup
    per distinct imported module;
  * `__init__.py` inference, via a single ancestor-files snapshot.

It is opt-in (`[dependents-inference].use_batched_python`) and conservative: anything it cannot
reproduce exactly causes it to return `MaybeReverseDependencyGraph(None)`, and the caller falls back
to the always-correct per-target algorithm.
"""

from __future__ import annotations

import os
from collections import defaultdict

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
from pants.core.util_rules.unowned_dependency_behavior import UnownedDependencyUsage
from pants.engine.addresses import Address
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import determine_explicitly_provided_dependencies
from pants.engine.intrinsics import digest_to_snapshot, get_digest_contents, path_globs_to_digest
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import (
    AllUnexpandedTargets,
    Dependencies,
    DependenciesRequest,
    InferDependenciesRequest,
    SpecialCasedDependencies,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet

# The dependency-inference backends whose edges this batched pass reproduces. Any other registered
# `InferDependenciesRequest` (e.g. pex-binary entry points, `python_distribution`s, or a plugin) is
# allowed only if it does not apply to any target in the repo (see `_is_eligible`).
_REPRODUCED_INFERENCE = frozenset({InferPythonImportDependencies, InferInitDependencies})


class PythonReverseDependencyGraphImpl(ReverseDependencyGraphImpl):
    pass


def _is_eligible(
    union_membership: UnionMembership,
    all_targets: AllUnexpandedTargets,
    python_infer: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> bool:
    """Only proceed if the batched pass can reproduce the per-target result exactly.

    Conservative by design: any condition we do not reproduce must be rejected here so the caller
    falls back to the (always-correct) per-target algorithm.
    """
    # `[python-infer]` settings that change which/whether edges are produced in ways we don't model.
    if python_infer.unowned_dependency_behavior == UnownedDependencyUsage.RaiseError:
        return False
    if python_infer.assets:
        return False
    if python_infer.ambiguity_resolution != AmbiguityResolution.none:
        return False

    # Any inference backend we don't reproduce (conftest, pex entry points, distributions, plugins)
    # is fine only as long as it applies to no target -- otherwise it would contribute edges.
    unreproduced = [
        req
        for req in union_membership.get(InferDependenciesRequest)
        if req not in _REPRODUCED_INFERENCE
    ]

    resolves: set[str] = set()
    for tgt in all_targets:
        # Parametrized addresses require `_fill_parameters`, which we do not reproduce.
        if tgt.address.parameters:
            return False
        # Special-cased dependency fields (e.g. `archive`'s `files`/`packages`) add edges.
        for field in tgt.field_values.values():
            if isinstance(field, SpecialCasedDependencies):
                return False
        if any(req.infer_from.is_applicable(tgt) for req in unreproduced):
            return False
        if tgt.has_field(PythonResolveField):
            resolves.add(tgt[PythonResolveField].normalized_value(python_setup))
    # Multiple resolves complicate owner disambiguation; only support the single-resolve case.
    if len(resolves) > 1:
        return False
    return True


@rule(desc="Map all targets to their dependents (batched, first-party Python)")
async def python_reverse_dependency_graph(
    request: PythonReverseDependencyGraphImpl,
    all_targets: AllUnexpandedTargets,
    union_membership: UnionMembership,
    python_infer: PythonInferSubsystem,
    python_setup: PythonSetup,
) -> MaybeReverseDependencyGraph:
    if not _is_eligible(union_membership, all_targets, python_infer, python_setup):
        return MaybeReverseDependencyGraph(None)

    address_to_dependents: defaultdict[Address, set[Address]] = defaultdict(set)
    # Per-target explicit `!`-ignores, applied to inferred edges too (mirrors `_get_imports_info`).
    address_to_ignores: dict[Address, set[Address]] = {}

    py_tgts = [t for t in all_targets if t.has_field(PythonSourceField)]
    py_fields = [t.get(PythonSourceField) for t in py_tgts]
    path_to_address = {f.file_path: t.address for t, f in zip(py_tgts, py_fields) if f.file_path}
    resolve = None
    if py_tgts and py_tgts[0].has_field(PythonResolveField):
        resolve = py_tgts[0][PythonResolveField].normalized_value(python_setup)

    # (1) Generator -> generated-target edges. `resolve_dependencies` injects a generator's
    # generated targets as its dependencies; reversed, every generated target is depended on by its
    # generator. Derivable directly from the (unexpanded) target set, with no rule calls.
    for tgt in all_targets:
        if tgt.address.is_generated_target:
            address_to_dependents[tgt.address].add(tgt.address.maybe_convert_to_target_generator())

    # (2) Explicit dependencies. Only a minority of targets set `dependencies=[...]`; resolve those
    # individually, reusing the production rule so semantics (parsing, ignores) match exactly.
    explicit_tgts = [t for t in all_targets if (t.get(Dependencies).value or ())]
    explicit_results = await concurrently(
        determine_explicitly_provided_dependencies(
            **implicitly(DependenciesRequest(t.get(Dependencies)))
        )
        for t in explicit_tgts
    )
    for tgt, epd in zip(explicit_tgts, explicit_results):
        ignores = set(epd.ignores)
        if ignores:
            address_to_ignores[tgt.address] = ignores
        for dep in epd.includes:
            if dep not in ignores:
                address_to_dependents[dep].add(tgt.address)

    # (3) First-party import inference, batched: one snapshot + one native parse of *all* sources,
    # then one owner lookup per distinct imported module.
    if py_tgts and python_infer.imports:
        digest = await path_globs_to_digest(PathGlobs(tuple(path_to_address.keys())))
        snapshot = await digest_to_snapshot(digest)
        parsed = await parse_python_dependencies(
            ParsePythonDependenciesRequest(SourceFiles(snapshot, ())), **implicitly()
        )
        # `parse_python_dependencies` strips source roots, so its keys are source-root-relative. We
        # key `path_to_address` by the unstripped path, so any mismatch means a non-root source root
        # is in play; rather than miss edges, decline and let the caller use the per-target path.
        # (Full source-root support is a follow-up.)
        if any(path not in path_to_address for path in parsed.path_to_deps):
            return MaybeReverseDependencyGraph(None)
        all_modules: set[str] = set()
        for file_deps in parsed.path_to_deps.values():
            all_modules.update(file_deps.imports.keys())
        sorted_modules = sorted(all_modules)
        owners_per_module = await concurrently(
            map_module_to_address(PythonModuleOwnersRequest(module, resolve), **implicitly())
            for module in sorted_modules
        )
        module_to_owners = dict(zip(sorted_modules, owners_per_module))
        for path, file_deps in parsed.path_to_deps.items():
            importer = path_to_address[path]
            ignores = address_to_ignores.get(importer, set())
            for module in file_deps.imports:
                owners = module_to_owners.get(module)
                if owners is None:
                    continue
                for owner in owners.unambiguous:
                    if owner != importer and owner not in ignores:
                        address_to_dependents[owner].add(importer)

    # (4) `__init__.py` inference, batched: each source depends on the owners of the `__init__.py`/
    # `.pyi` files in its package chain. We find the *owned* init files directly from the target set
    # (an unowned init file produces no edge anyway), applying the same empty-file filtering as
    # `find_ancestor_files`. (We can't simply call `find_ancestor_files` over all sources at once:
    # it subtracts its `input_files` from candidates, which would drop init files that are
    # themselves targets -- the per-target path avoids this by passing one file at a time.)
    if py_tgts and python_infer.init_files is not InitFilesInference.never:
        init_candidates = [
            p
            for p in path_to_address
            if os.path.basename(p) in ("__init__.py", "__init__.pyi")
        ]
        if python_infer.init_files is InitFilesInference.content_only and init_candidates:
            contents = await get_digest_contents(**implicitly({PathGlobs(init_candidates): PathGlobs}))
            init_paths = {fc.path for fc in contents if fc.content.strip()}
        else:
            init_paths = set(init_candidates)
        for path, importer in path_to_address.items():
            ignores = address_to_ignores.get(importer, set())
            package = ""
            chain = [""]
            for component in os.path.dirname(path).split(os.sep):
                package = os.path.join(package, component) if package else component
                chain.append(package)
            for pkg in chain:
                for name in ("__init__.py", "__init__.pyi"):
                    init_path = os.path.join(pkg, name) if pkg else name
                    if init_path == path or init_path not in init_paths:
                        continue
                    owner = path_to_address.get(init_path)
                    if owner is not None and owner != importer and owner not in ignores:
                        address_to_dependents[owner].add(importer)

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
