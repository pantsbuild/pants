# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Iterable

import hcl2

from pants.backend.terraform.target_types import TerraformModuleSources
from pants.base.specs import AddressSpecs, MaybeEmptySiblingAddresses
from pants.engine.fs import Digest, DigestContents
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    Targets,
)
from pants.engine.unions import UnionRule


class InferTerraformModuleDependenciesRequest(InferDependenciesRequest):
    infer_from = TerraformModuleSources


class PurePath:
    pass


# PurePath does not have the Path.resolve method which resolves ".." components, thus we need to
# code our own version for PurePath's.
def resolve_pure_path(base: PurePath, relative_path: PurePath) -> PurePath:
    parts = list(base.parts)
    for component in relative_path.parts:
        if component == ".":
            pass
        elif component == "..":
            if not parts:
                raise ValueError(f"Relative path {relative_path} escapes from path {base}.")
            parts.pop()
        else:
            parts.append(component)

    return PurePath(*parts)


def extract_module_source_paths(path: PurePath, raw_content: bytes) -> Iterable[str]:
    content = raw_content.decode("utf-8")
    parsed_content = hcl2.loads(content)

    # Note: The `module` key is a list where each entry is a dict with a single entry where the key is the
    # module name and the values are a dict for that module's actual values.
    paths = []
    for wrapped_module in parsed_content.get("module", []):
        values = wrapped_module.values()[0]  # the module is the sole entry in `wrapped_module`
        source = values.get("source", "")

        # Local paths to modules must begin with "." or ".." as per
        # https://www.terraform.io/docs/language/modules/sources.html#local-paths.
        if source.startswith("./") or source.startswith("../"):
            try:
                resolved_path = resolve_pure_path(path, PurePath(source))
                paths.append(str(resolved_path))
            except ValueError:
                pass

    return paths


@rule
async def infer_terraform_module_dependencies(
    request: InferTerraformModuleDependenciesRequest,
) -> InferredDependencies:
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    digest_contents = await Get(DigestContents, Digest, hydrated_sources.snapshot.digest)

    # Find all local modules referenced by this module.
    paths = []
    for entry in digest_contents:
        if entry.path.endswith(".tf"):
            paths.extend(extract_module_source_paths(entry.content))

    # For each path, see if there is a `terraform_module` target at the specified path.
    candidate_targets = await Get(
        Targets, AddressSpecs([MaybeEmptySiblingAddresses(path) for path in paths])
    )
    terraform_module_targets = [
        tgt for tgt in candidate_targets if tgt.has_field(TerraformModuleSources)
    ]
    return InferredDependencies(terraform_module_targets)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferTerraformModuleDependenciesRequest),
    ]
